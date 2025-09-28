import Layout from './components/Layout';
import ApiErrorListener from './components/ApiErrorListener';
import Toaster from './components/ui/toaster';
import { ThemeProvider } from './components/theme-provider';
import AppRoutes from './routes';

const App = () => (
  <ThemeProvider>
    <ApiErrorListener />
    <Layout>
      <AppRoutes />
    </Layout>
    <Toaster />
  </ThemeProvider>
);

export default App;
