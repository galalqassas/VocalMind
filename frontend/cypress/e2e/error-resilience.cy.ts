describe('Error resilience and edge cases', () => {
  it('displays an error message when login credentials fail', () => {
    cy.useE2eApiFixtures({ auth: false });

    cy.intercept('POST', '**/api/v1/auth/login/access-token', {
      statusCode: 401,
      body: { detail: 'Incorrect email or password' },
    }).as('loginFail');

    cy.visit('/');
    cy.get('input[type="email"]').type('wrong@example.com');
    cy.get('input[type="password"]').type('badpassword');
    cy.contains('button', 'Sign In').click();

    cy.wait('@loginFail');
    cy.location('pathname').should('eq', '/');
    cy.get('input[type="email"]').should('be.visible');
  });

  it('shows the dashboard error state when the stats API fails', () => {
    cy.visitAs('manager', '/manager', {
      dashboard: { statusCode: 500 },
    });

    cy.contains('Failed to load dashboard data').should('be.visible');
  });

  it('shows the agent calls error state when the interactions API fails', () => {
    cy.visitAs('agent', '/agent/calls', {
      interactions: { statusCode: 500 },
    });

    cy.contains('Failed to load calls').should('be.visible');
  });

  it('allows cancelling the logout confirmation dialog', () => {
    cy.loginAs('manager');
    cy.contains('Average Score').should('be.visible');

    cy.get('[data-cy="user-menu-trigger"]').click();
    cy.contains('Log out').click();

    // Dialog should appear
    cy.contains('Are you sure you want to log out').should('be.visible');
    cy.contains('button', 'Cancel').click();

    // Should remain on dashboard, not logged out
    cy.location('pathname').should('eq', '/manager');
    cy.contains('Average Score').should('be.visible');
  });

  it('redirects an unauthenticated user from agent routes to login', () => {
    cy.useE2eApiFixtures({ auth: false });
    cy.visit('/agent');

    cy.location('pathname').should('eq', '/');
    cy.contains('Welcome to VocalMind').should('be.visible');
  });
});
