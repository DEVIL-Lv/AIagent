import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Settings from './pages/Settings';
import Analysis from './pages/Analysis';
import MainLayout from './layouts/MainLayout';
import ErrorBoundary from './components/ErrorBoundary';

const App: React.FC = () => {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route element={<MainLayout />}>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/analysis" element={<Analysis />} />
            <Route path="/settings" element={<Settings />} />
          </Route>

          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  );
};

export default App;
