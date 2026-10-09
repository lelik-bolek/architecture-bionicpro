# Архитектурное решение: Управление учетными данными и безопасность (Задание 1)

## 1. Контекст и решаемые проблемы
В результате инцидента безопасности с использованием уязвимости перехвата токенов в публичном клиенте произошла утечка данных. Кроме того, выход BionicPRO на международные рынки накладывает строгие требования регуляторов (152-ФЗ, GDPR, HIPAA) по локализации хранения персональных (ПДн) и медицинских данных граждан в странах их присутствия.

## 2. Архитектура To-Be и ключевые решения

### 2.1. Трансграничная федерация удостоверений (Federated Identity)
- В стране филиала/представительства развертывается локальный Identity Provider (Active Directory / OpenLDAP / Local Keycloak), хранящий данные учетных записей локальных резидентов.
- Центральный Keycloak компании BionicPRO выступает в роли Identity Broker. Аутентификация иностранных пользователей происходит через редирект на их доверенный IdP по протоколам SAML 2.0 или OIDC Federation.
- В контур BionicPRO передается только криптографически подписанное утверждение (SAML assertion / OIDC ID Token).
- Выполняется маппинг внешних групп на внутренние роли системы (`prothetic_user`), при этом персональные и медицинские данные не покидают страну происхождения, требования законодательства не нарушаются.

### 2.2. Защита токенов и паттерн BFF (Backend for Frontend)
- Для исключения передачи и хранения access- и refresh-токенов на стороне клиентских приложений (SPA / Mobile) внедрен защитный шлюз BFF (API Gateway).
- Фронтенд взаимодействует с BFF исключительно через безопасные сессионные куки с флагами `HttpOnly`, `Secure`, `SameSite=Strict`.
- BFF берет на себя хранение токенов в защищенной серверной сессии, автоматическое обновление через refresh_token и проксирование запросов к внутреннему API с подстановкой заголовка `Authorization: Bearer <access_token>`.

### 2.3. Внедрение OAuth 2.0 Authorization Code Flow с расширением PKCE
- Для предотвращения атак перехвата авторизационного кода (Authorization Code Interception Attack) стандартный Code Grant дополнен расширением PKCE (Proof Key for Code Exchange, RFC 7636).
- На авторизационном сервере (Keycloak) для клиента зафиксировано обязательное использование метода проверки `code_challenge_method = S256`.

![Схема решения](../schemas/task1_c4_identity.png)

## 3. Реализация PKCE Flow (Задача 2)

### 3.1. Принудительный PKCE на сервере авторизации (Keycloak)
- Для публичного клиента `reports-frontend` в `keycloak/realm-export.json` установлен атрибут `pkce.code.challenge.method = S256`: сервер авторизации отклоняет запросы к `/protocol/openid-connect/auth` без валидной пары `code_challenge` + `code_challenge_method=S256` (ошибка `invalid_request: Missing parameter: code_challenge_method`).
- Прямой грант отключен (`directAccessGrantsEnabled = false`): аутентификация по логину/паролю напрямую через `/protocol/openid-connect/token` (`grant_type=password`, Direct Access Grants) запрещена — все пользователи проходят единый безопасный SSO Authorization Code Flow.

### 3.2. PKCE на стороне SPA (React)
- SPA инициализирует `keycloak-js` с `initOptions: { pkceMethod: 'S256', onLoad: 'login-required' }` (`frontend/src/App.tsx`).
- Библиотека генерирует криптостойкий `code_verifier`, вычисляет `code_challenge = BASE64URL(SHA256(code_verifier))` и передает challenge в запросе авторизации, а verifier — только при обмене кода на токен. Перехваченный авторизационный код бесполезен без `code_verifier`, который хранится исключительно в браузере легитимного клиента и никогда не передается по фронт-каналу.

### 3.3. Протокол верификации PKCE (RFC 7636)

**Шаг 1 — запрос авторизации (front-channel, браузер → Keycloak).** В запросе `/auth` присутствуют `code_challenge` и `code_challenge_method=S256`:

```http
GET /realms/reports-realm/protocol/openid-connect/auth?client_id=reports-frontend&response_type=code&scope=openid&redirect_uri=http%3A%2F%2Flocalhost%3A3000%2F&code_challenge=<BASE64URL(SHA256(code_verifier))>&code_challenge_method=S256
```

Keycloak сохраняет `code_challenge` вместе с выданным авторизационным кодом. Благодаря атрибуту `pkce.code.challenge.method=S256` запрос без `code_challenge` отклоняется с ошибкой `invalid_request: Missing parameter: code_challenge_method`.

**Шаг 2 — обмен кода на токен (back-channel, браузер → Keycloak).** В запросе `/token` присутствует `code_verifier`:

```http
POST /realms/reports-realm/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code&client_id=reports-frontend&code=<authorization_code>&redirect_uri=http%3A%2F%2Flocalhost%3A3000%2F&code_verifier=<исходный code_verifier>
```

Keycloak вычисляет `BASE64URL(SHA256(code_verifier))` и сравнивает результат с `code_challenge`, сохраненным на шаге 1. При несовпадении возвращается ошибка `invalid_grant`, токены не выпускаются.

### 3.4. Почему PKCE предотвращает Authorization Code Interception Attack

- В классическом Authorization Code Flow без PKCE авторизационный код — единственный секрет фронт-канала: перехватив его (вредоносное приложение на устройстве, перехват redirect через кастомную URL-схему, журналы/Referer), атакующий немедленно обменял бы код на пару access/refresh токенов — именно так произошел инцидент в BionicPRO.
- PKCE (RFC 7636) привязывает авторизационный код к конкретному экземпляру клиента: `code_verifier` — криптостойкая случайная строка (43–128 символов), которая генерируется и хранится только в памяти браузера легитимного клиента и никогда не покидает фронт-канал; по сети передается лишь необратимый `code_challenge` (SHA-256).
- Перехваченный код бесполезен: на шаге обмена `/token` атакующий не сможет предъявить корректный `code_verifier`, сервер вернет `invalid_grant`. Восстановить verifier из challenge невозможно — SHA-256 однонаправлен.
- Тем самым устранена исходная уязвимость BionicPRO: компрометация авторизационного кода больше не приводит к компрометации токенов и ПДн. Отключение `directAccessGrantsEnabled` дополнительно закрывает обходной канал получения токенов по логину/паролю (`grant_type=password`) в обход SSO-потока.

## 4. Верификация решения

- Импорт realm подтвержден логами Keycloak 21.1.2: `Realm 'reports-realm' imported`, `KC-SERVICES0032: Import finished successfully` (`docker compose logs keycloak`).
- Быстрая проверка в браузере: открыть `http://localhost:3000` → редирект на страницу входа Keycloak (`reports-realm`) → войти `user1` / `password123` → редирект обратно на SPA с кодом → обмен кода на токен с `code_verifier`. В DevTools (вкладка Network) в запросе `/auth` видны `code_challenge` и `code_challenge_method=S256`, в запросе `/token` — `code_verifier`.