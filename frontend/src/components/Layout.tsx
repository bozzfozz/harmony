import { ReactNode } from "react";
import { Outlet } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

import Sidebar from "./Sidebar";
import { Button } from "./ui/button";

interface LayoutProps {
  header: ReactNode;
  isSidebarOpen: boolean;
  onSidebarOpenChange: (open: boolean) => void;
}

const Layout = ({ header, isSidebarOpen, onSidebarOpenChange }: LayoutProps) => {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="sticky top-0 z-50">{header}</div>

      <Dialog.Root open={isSidebarOpen} onOpenChange={onSidebarOpenChange}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-background/80 backdrop-blur-sm data-[state=open]:animate-fade-in data-[state=closed]:animate-fade-out" />
          <Dialog.Content className="radix-side-drawer fixed inset-y-0 left-0 z-50 w-72 border-r border-border/60 bg-sidebar p-4 text-sidebar-foreground shadow-xl data-[state=open]:animate-drawer-in data-[state=closed]:animate-drawer-out">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Navigation</h2>
              <Dialog.Close asChild>
                <Button variant="ghost" size="icon">
                  <X className="h-5 w-5" />
                  <span className="sr-only">Close navigation</span>
                </Button>
              </Dialog.Close>
            </div>
            <Sidebar onNavigate={() => onSidebarOpenChange(false)} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <div className="flex">
        <aside className="fixed inset-y-0 left-0 hidden w-64 flex-shrink-0 border-r border-border/60 bg-sidebar/90 backdrop-blur md:block">
          <Sidebar />
        </aside>
        <main className="flex-1 px-4 pb-8 pt-6 md:ml-64 md:px-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default Layout;
