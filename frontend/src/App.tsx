import React from 'react';
import { ReactKeycloakProvider } from '@react-keycloak/web';
import Keycloak, { KeycloakConfig, KeycloakInitOptions } from 'keycloak-js';
import ReportPage from './components/ReportPage';

const keycloakConfig: KeycloakConfig = {
  url: process.env.REACT_APP_KEYCLOAK_URL,
  realm: process.env.REACT_APP_KEYCLOAK_REALM || "",
  clientId: process.env.REACT_APP_KEYCLOAK_CLIENT_ID || ""
};

const keycloak = new Keycloak(keycloakConfig);

// PKCE (RFC 7636): keycloak-js генерирует code_verifier, вычисляет
// code_challenge = BASE64URL(SHA256(code_verifier)) и отправляет challenge
// в запросе авторизации (/auth), а verifier — только при обмене кода на токен (/token).
const keycloakInitOptions: KeycloakInitOptions = {
  onLoad: 'login-required',
  pkceMethod: 'S256',
  checkLoginIframe: false,
  enableLogging: true
};

const App: React.FC = () => {
  return (
    <ReactKeycloakProvider
      authClient={keycloak}
      initOptions={keycloakInitOptions}
    >
      <div className="App">
        <ReportPage />
      </div>
    </ReactKeycloakProvider>
  );
};

export default App;