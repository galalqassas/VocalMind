describe("Universal login entry", () => {
  it("shows the login form at the root route", () => {
    cy.useE2eApiFixtures({ auth: false });
    cy.visit("/");

    cy.contains("Welcome to VocalMind").should("be.visible");
    cy.get('input[type="email"]').should("be.visible");
    cy.contains("Manager Portal").should("not.exist");
    cy.contains("Agent Portal").should("not.exist");
  });

  it("redirects legacy /login to the root login screen", () => {
    cy.useE2eApiFixtures({ auth: false });
    cy.visit("/login");

    cy.location("pathname").should("eq", "/");
    cy.contains("Welcome to VocalMind").should("be.visible");
  });
});
