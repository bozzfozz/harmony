import { ReactNode, useState } from 'react';

import Navbar from './Navbar';
import Sidebar from './Sidebar';

export interface LayoutProps {
  children: ReactNode;
}

const Layout = ({ children }: LayoutProps) => {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <Sidebar open={mobileOpen} onOpenChange={setMobileOpen} />
      <div className="flex min-h-screen w-full flex-1 flex-col lg:ml-72">
        <Navbar onMenuClick={() => setMobileOpen(true)} />
        <main className="flex-1 bg-muted/40 px-4 py-6 sm:px-8 lg:px-10">
          <div className="mx-auto w-full max-w-6xl space-y-6">{children}</div>
        </main>
      </div>
    </div>
  );
};

export default Layout;
