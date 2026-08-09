// SteelDigitize Pro — 入口（工作台 MVP：工作台/审核区/资料库/品名库/设置）
import { ToastProvider } from './hooks/useToast';
import { NavProvider } from './contexts/NavContext';
import { QueueProvider } from './contexts/QueueContext';
import ErrorBoundary from './components/ErrorBoundary';
import Layout from './components/Layout';
import WorkbenchPage from './pages/WorkbenchPage';
import ReviewPage from './pages/ReviewPage';
import LibraryPage from './pages/LibraryPage';
import MaterialsPage from './pages/MaterialsPage';
import SettingsPage from './pages/SettingsPage';

export default function App() {
  return (
    <ToastProvider>
      <NavProvider>
        <QueueProvider>
          <ErrorBoundary>
            <Layout>
              <WorkbenchPage />
              <ReviewPage />
              <LibraryPage />
              <MaterialsPage />
              <SettingsPage />
            </Layout>
          </ErrorBoundary>
        </QueueProvider>
      </NavProvider>
    </ToastProvider>
  );
}
