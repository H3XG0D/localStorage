/**
 * Tests for LoginPage: render, form submit, redirect via useEffect.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from './mocks/server';

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

import LoginPage from '../pages/auth/LoginPage';
import { AuthProvider } from '../context/AuthContext';

function renderLogin() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────

describe('LoginPage', () => {
  beforeEach(() => {
    localStorage.clear();
    mockNavigate.mockClear();
  });

  it('renders login form', () => {
    renderLogin();
    expect(screen.getByPlaceholderText('Введите логин')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Введите пароль')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /войти/i })).toBeInTheDocument();
  });

  it('shows error on wrong credentials', async () => {
    server.use(
      http.post('http://localhost:8000/auth/login', () =>
        HttpResponse.json({ detail: 'Invalid credentials' }, { status: 401 })
      )
    );
    renderLogin();
    fireEvent.change(screen.getByPlaceholderText('Введите логин'), { target: { value: 'bad' } });
    fireEvent.change(screen.getByPlaceholderText('Введите пароль'), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: /войти/i }));
    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
    });
  });

  it('navigates after successful login', async () => {
    renderLogin();
    fireEvent.change(screen.getByPlaceholderText('Введите логин'), { target: { value: 'trader1' } });
    fireEvent.change(screen.getByPlaceholderText('Введите пароль'), { target: { value: 'traderpass' } });
    fireEvent.click(screen.getByRole('button', { name: /войти/i }));
    await waitFor(() => {
      // After login, navigate is called at least once (either to '/' or to role home)
      expect(mockNavigate).toHaveBeenCalled();
    }, { timeout: 3000 });
  });

  it('does not call navigate during render (no render-time navigate)', () => {
    renderLogin();
    // No user stored → navigate should NOT be called during render
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
