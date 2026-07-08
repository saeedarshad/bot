import { createContext, useContext } from "react";

const AuthContext = createContext({ me: null, reload: () => {}, logout: () => {} });

export function AuthProvider({ value, children }) {
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
