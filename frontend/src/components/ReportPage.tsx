import React, { useState } from 'react';
import { useKeycloak } from '@react-keycloak/web';

interface ReportRecord {
  report_date: string;
  total_steps: number;
  active_time_seconds: number;
  battery_drain_avg: number;
  load_level_max: number;
}

const ReportPage: React.FC = () => {
  const { keycloak, initialized } = useKeycloak();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [records, setRecords] = useState<ReportRecord[]>([]);

  const formatSteps = (steps: number): string => {
    return steps.toLocaleString('ru-RU');
  };

  const formatDuration = (seconds: number): string => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) {
      return `${h}ч ${m}м ${s}с`;
    }
    if (m > 0) {
      return `${m}м ${s}с`;
    }
    return `${s}с`;
  };

  const downloadReport = async () => {
    if (!keycloak?.authenticated) {
      setError('Пользователь не авторизован. Выполните вход в систему.');
      return;
    }

    if (!keycloak?.token) {
      setError('Отсутствует токен авторизации.');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setWarning(null);
      setRecords([]);

      const apiUrl = process.env.REACT_APP_API_URL || 'http://localhost:8000';
      const response = await fetch(`${apiUrl}/reports`, {
        headers: {
          'Authorization': `Bearer ${keycloak.token}`,
          'Accept': 'application/json',
        },
      });

      if (!response.ok) {
        if (response.status === 401) {
          setError('Ошибка авторизации. Пожалуйста, войдите в систему заново.');
          return;
        }
        if (response.status === 500) {
          setError('Ошибка сервера. Попробуйте позже.');
          return;
        }
        setError(`Ошибка API: ${response.status} ${response.statusText}`);
        return;
      }

      const data = await response.json();

      // Проверяем наличие warning в ответе
      if (data.warning) {
        setWarning(data.warning);
      }

      // Если пришёл массив записей — отображаем их
      if (Array.isArray(data)) {
        setRecords(data);
      } else if (data.records && Array.isArray(data.records)) {
        setRecords(data.records);
      } else if (data.data && Array.isArray(data.data)) {
        setRecords(data.data);
      } else {
        setError('Неизвестный формат ответа сервера.');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка сети. Проверьте соединение.');
    } finally {
      setLoading(false);
    }
  };

  if (!initialized) {
    return <div className="flex items-center justify-center min-h-screen bg-gray-100">Загрузка...</div>;
  }

  if (!keycloak.authenticated) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <div className="p-8 bg-white rounded-lg shadow-md text-center">
          <p className="mb-4 text-gray-700">Для доступа к отчётам выполните вход в систему.</p>
          <button
            onClick={() => keycloak.login()}
            className="px-6 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors"
          >
            Войти
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100 p-4">
      <div className="p-8 bg-white rounded-lg shadow-md w-full max-w-4xl">
        <h1 className="text-2xl font-bold mb-6 text-gray-800">Отчёты об использовании</h1>

        <button
          onClick={downloadReport}
          disabled={loading || !keycloak.authenticated}
          className={`px-6 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors ${
            loading || !keycloak.authenticated
              ? 'opacity-50 cursor-not-allowed'
              : ''
          }`}
        >
          {loading ? 'Формирование отчёта...' : 'Получить отчёт'}
        </button>

        {/* Warning баннер */}
        {warning && (
          <div className="mt-4 p-4 bg-yellow-100 border border-yellow-300 text-yellow-800 rounded">
            ⚠️ {warning}
          </div>
        )}

        {/* Сообщение об ошибке */}
        {error && (
          <div className="mt-4 p-4 bg-red-100 border border-red-300 text-red-700 rounded">
            ❌ {error}
          </div>
        )}

        {/* Таблица с записями отчёта */}
        {records.length > 0 && (
          <div className="mt-6 overflow-x-auto">
            <table className="min-w-full bg-white border border-gray-200 rounded">
              <thead>
                <tr className="bg-gray-50">
                  <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700 border-b">Дата</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700 border-b">Шаги</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700 border-b">Активность</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700 border-b">Расход батареи, %</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700 border-b">Пиковая нагрузка</th>
                </tr>
              </thead>
              <tbody>
                {records.map((record, index) => (
                  <tr
                    key={index}
                    className={`border-b hover:bg-gray-50 ${index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}`}
                  >
                    <td className="px-4 py-3 text-sm text-gray-800">
                      {new Date(record.report_date).toLocaleDateString('ru-RU')}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-800">
                      {formatSteps(record.total_steps)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-800">
                      {formatDuration(record.active_time_seconds)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-800">
                      {record.battery_drain_avg.toFixed(1)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-800">
                      {record.load_level_max}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default ReportPage;