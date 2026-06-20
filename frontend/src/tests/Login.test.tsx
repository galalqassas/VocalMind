import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { MemoryRouter } from "react-router";
import Login from "../app/pages/Login";

vi.mock("../app/contexts/AuthContext", () => ({
  useAuth: () => ({
    login: vi.fn(),
    user: null,
    isAuthenticated: false,
    isLoading: false,
  }),
}));

describe("Login", () => {
  it("renders the universal sign-in form", () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>,
    );

    expect(screen.getByText("Welcome to VocalMind")).toBeInTheDocument();
    expect(screen.getByText("Sign in to your dashboard")).toBeInTheDocument();
    expect(screen.getByText("Work Email")).toBeInTheDocument();
    expect(screen.getByText("Password")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("employee@vocalmind.ai")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Sign In/i })).toBeInTheDocument();
  });

  it("does not mention separate manager or agent portals", () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>,
    );

    expect(screen.queryByText("Manager Portal")).not.toBeInTheDocument();
    expect(screen.queryByText("Agent Portal")).not.toBeInTheDocument();
  });
});
