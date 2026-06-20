// Import custom Cypress commands
import './commands';

import '@cypress/code-coverage/support';

beforeEach(() => {
  cy.clearCookies();
  cy.clearLocalStorage();
  cy.useE2eApiFixtures();
});
