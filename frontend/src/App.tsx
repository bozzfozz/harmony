import Layout from './components/Layout';
import ApiErrorListener from './components/ApiErrorListener';
import Toaster from './components/ui/toaster';
import { ToastProvider } from './components/ui/toast';
import { ThemeProvider } from './components/theme-provider';
import AppRoutes from './routes';

const App = () => (
  <ThemeProvider>
    <ToastProvider duration={6000} swipeDirection="right">
      <ApiErrorListener />
      <Layout>
        <AppRoutes />
      </Layout>
      <Toaster />
    </ToastProvider>
  </ThemeProvider>
);

export default App;
