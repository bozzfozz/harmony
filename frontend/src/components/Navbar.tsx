import { useState } from "react";
import { Link } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { Menu, X } from "lucide-react";
import Sidebar from "./Sidebar";
import { Button } from "./ui/button";
import DarkModeToggle from "./DarkModeToggle";

const Navbar = () => {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-border/60 bg-navbar/90 backdrop-blur">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-4 text-navbar-foreground md:px-8">
        <div className="flex items-center gap-3">
          <Dialog.Root open={mobileOpen} onOpenChange={setMobileOpen}>
            <Dialog.Trigger asChild>
              <Button variant="ghost" size="icon" className="md:hidden">
                <Menu className="h-5 w-5" />
                <span className="sr-only">Open navigation</span>
              </Button>
            </Dialog.Trigger>
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
                <Sidebar onNavigate={() => setMobileOpen(false)} />
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
          <Link to="/dashboard" className="text-xl font-semibold tracking-tight">
            Harmony
          </Link>
        </div>
        <div className="flex items-center gap-3">
          <DarkModeToggle />
          <div className="hidden text-sm font-medium text-muted-foreground md:block">
            Willkommen zurück, User
          </div>
          <Button variant="outline" className="border-border/80 text-navbar-foreground">
            User Menü
          </Button>
        </div>
      </div>
    </header>
  );
};

export default Navbar;
