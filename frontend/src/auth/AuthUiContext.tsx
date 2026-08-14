import {
  createContext,
  type ReactNode,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
} from 'react';


export type AuthUiState = 'unknown' | 'authorized' | 'unauthenticated' | 'unauthorized' | 'public';

interface AuthUiContextValue {
  state: AuthUiState;
  setState: (state: AuthUiState) => void;
}

const AuthUiContext = createContext<AuthUiContextValue | null>(null);

export function AuthUiProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthUiState>('unknown');
  const value = useMemo(() => ({ state, setState }), [state]);

  return <AuthUiContext.Provider value={value}>{children}</AuthUiContext.Provider>;
}

export function useAuthUi() {
  const value = useContext(AuthUiContext);
  if (value === null) {
    throw new Error('AuthUiProvider is required.');
  }
  return value;
}

export function useReportAuthUiState(state: AuthUiState) {
  const { setState } = useAuthUi();

  // Layout timing prevents the previous route's protected chrome from painting
  // while the newly requested route is still resolving its own access state.
  useLayoutEffect(() => {
    setState(state);
  }, [setState, state]);
}
