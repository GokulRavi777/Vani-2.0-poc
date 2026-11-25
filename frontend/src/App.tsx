import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LoginPage } from './pages/LoginPage';
import { SkillSelectionPage } from './pages/SkillSelectionPage';
import { AssessmentSetupPage } from './pages/AssessmentSetupPage';
import { InterviewPage } from './pages/InterviewPage';
import { CompletionPage } from './pages/CompletionPage';

const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { token, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center text-slate-900">
        <span className="w-6 h-6 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/skills"
            element={
              <ProtectedRoute>
                <SkillSelectionPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/assessment/setup"
            element={
              <ProtectedRoute>
                <AssessmentSetupPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/interview/:sessionId"
            element={
              <ProtectedRoute>
                <InterviewPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/assessment/completed/:sessionId"
            element={
              <ProtectedRoute>
                <CompletionPage />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
};

export default App;
