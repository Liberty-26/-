// SteelDigitize Pro — 入口（全部页面常驻，切 Tab 状态保持）
import { ToastProvider } from './hooks/useToast';
import Layout from './components/Layout';
import UploadPage from './pages/UploadPage';
import HistoryPage from './pages/HistoryPage';
import AgentPage from './pages/AgentPage';
import MaterialsPage from './pages/MaterialsPage';
import SettingsPage from './pages/SettingsPage';

export default function App() {
  return (
    <ToastProvider>
      <Layout>
        {(active) => {
          switch (active) {
            case 'upload': return <UploadPage />;
            case 'history': return <HistoryPage />;
            case 'agent': return <AgentPage />;
            case 'materials': return <MaterialsPage />;
            case 'settings': return <SettingsPage />;
          }
        }}
      </Layout>
    </ToastProvider>
  );
}
