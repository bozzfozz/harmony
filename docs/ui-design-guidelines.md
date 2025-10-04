# Harmony Web UI Design Guidelines

Diese verbindlichen Richtlinien definieren das Designsystem der Harmony-Web-UI. Alle zukünftigen Frontend-Implementierungen müssen mit diesen Vorgaben kompatibel sein. Die Gestaltung orientiert sich am Portacker-Referenzlayout und ist für ein React + Vite + TypeScript + Tailwind + shadcn/ui + Radix Stack optimiert.

## 1. Farben

### Light Mode
- **Hintergrund:** `#ffffff`
- **Primärer Text:** `#1e293b`
- **Sekundärer Text:** `#475569`
- **Akzent (Interaktionen, aktive Elemente):** Indigo-600 `#4f46e5`

### Dark Mode
- **Hintergrund:** `#0f172a`
- **Primärer Text:** `#f8fafc`
- **Sekundärer Text:** `#cbd5e1`
- **Akzent (Interaktionen, aktive Elemente):** Indigo-500 `#6366f1`

### Statusfarben (Modus-übergreifend)
- **Erfolg:** Grün `#22c55e`
- **Fehler:** Rot `#ef4444`
- **Warnung:** Gelb `#f59e0b`
- **Info:** Blau `#3b82f6`

## 2. Typografie
- **Primäre Schriftart:** `"Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
- **Größen & Gewichtungen:**
  - Basistext: `text-sm` (`font-normal`)
  - Überschriften: `text-xl font-bold`
  - Card-Titel & Sektionen: `text-lg font-semibold`
  - Muted/Meta: `text-xs text-gray-500`
- Headline-Kapitalisierung: Satzanfang groß, rest gemäß deutscher Rechtschreibung.

## 3. Spacing & Layout
- **Globales Spacing:** Verwende `p-4`, `m-4`, `gap-4` als Standardabstände.
- **Grid-Verhalten:**
  - Dashboard: `lg:grid-cols-3`
  - Mobile: `grid-cols-1`
- **Cards:** `rounded-xl shadow-sm p-6 bg-white dark:bg-slate-900 border border-slate-200/60 dark:border-slate-800`
- **Maximale Inhaltsbreite:** `max-w-7xl mx-auto` für Hauptinhalte.

## 4. Komponenten
Alle Beispiele verwenden shadcn/ui-Komponenten mit Tailwind-Styling und folgen den Farb- und Typografie-Vorgaben.

### 4.1 Navbar
- Sticky am oberen Rand (`sticky top-0 z-50`).
- Höhe 64px (`h-16`).
- Untere Border (`border-b border-slate-200 dark:border-slate-800`).
- Hintergrund wechselt mit Theme (`bg-white/80 dark:bg-slate-900/80 backdrop-blur`).

```tsx
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";

export function Navbar() {
  return (
    <header className="sticky top-0 z-50 h-16 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur">
      <div className="mx-auto flex h-full max-w-7xl items-center justify-between px-4">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold text-slate-900 dark:text-slate-100">Harmony</span>
          <nav className="hidden items-center gap-4 text-sm text-slate-600 dark:text-slate-300 md:flex">
            <a className="transition-colors hover:text-slate-900 dark:hover:text-slate-50" href="#dashboard">Dashboard</a>
            <a className="transition-colors hover:text-slate-900 dark:hover:text-slate-50" href="#projects">Projekte</a>
            <a className="transition-colors hover:text-slate-900 dark:hover:text-slate-50" href="#settings">Einstellungen</a>
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" className="hidden md:inline-flex">Feedback</Button>
          <ThemeToggle />
          <Button>Neues Projekt</Button>
        </div>
      </div>
    </header>
  );
}
```

### 4.2 Sidebar / Drawer
- Desktop: permanente Sidebar (`w-64`, `border-r`).
- Unter `<md`: als Drawer mit Slide-in/out (Framer Motion) und Radix Dialog/Sheet.
- Collapsible Navigation mit Icons (`lucide-react`, Größe `h-5 w-5`).

```tsx
import { Home, Settings, Users } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";

const navItems = [
  { label: "Übersicht", icon: Home, href: "#dashboard" },
  { label: "Teams", icon: Users, href: "#teams" },
  { label: "Einstellungen", icon: Settings, href: "#settings" },
];

export function Sidebar() {
  const [open, setOpen] = useState(false);

  const NavLinks = (
    <nav className="flex flex-1 flex-col gap-2 p-4">
      {navItems.map(({ label, icon: Icon, href }) => (
        <a
          key={label}
          href={href}
          className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-50"
        >
          <Icon className="h-5 w-5" />
          {label}
        </a>
      ))}
    </nav>
  );

  return (
    <>
      <div className="hidden h-full w-64 border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 md:flex">
        {NavLinks}
      </div>

      <div className="md:hidden">
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" className="inline-flex items-center gap-2">
              <span>Menü</span>
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-64 border-r border-slate-200 bg-white p-0 dark:border-slate-800 dark:bg-slate-900">
            <AnimatePresence mode="wait">
              {open && (
                <motion.div
                  initial={{ x: -32, opacity: 0 }}
                  animate={{ x: 0, opacity: 1 }}
                  exit={{ x: -32, opacity: 0 }}
                  transition={{ type: "spring", stiffness: 260, damping: 24 }}
                  className="h-full"
                >
                  {NavLinks}
                </motion.div>
              )}
            </AnimatePresence>
          </SheetContent>
        </Sheet>
      </div>
    </>
  );
}
```

### 4.3 Tabs
- Verwende shadcn/ui Tabs. Aktive Tabfarbe Indigo, inaktive Tabfarbe `text-slate-500`.
- Tabs responsiv auf einer Zeile scrollfähig (`overflow-x-auto`).

```tsx
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function HarmonyTabs() {
  return (
    <Tabs defaultValue="overview" className="w-full">
      <TabsList className="h-10 overflow-x-auto rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
        <TabsTrigger value="overview" className="data-[state=active]:bg-white data-[state=active]:text-indigo-600 dark:data-[state=active]:bg-slate-900 dark:data-[state=active]:text-indigo-400">
          Übersicht
        </TabsTrigger>
        <TabsTrigger value="activity">Aktivität</TabsTrigger>
        <TabsTrigger value="analytics">Analytics</TabsTrigger>
      </TabsList>
      <TabsContent value="overview" className="mt-6">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {/* Karteninhalt hier */}
        </div>
      </TabsContent>
      <TabsContent value="activity">Aktivität</TabsContent>
      <TabsContent value="analytics">Analytics</TabsContent>
    </Tabs>
  );
}
```

### 4.4 Cards
- Verwenden `rounded-xl shadow-sm p-6`.
- Hintergrund entsprechend Theme, Status-Chips nutzen Statusfarben.

```tsx
import { TrendingUp } from "lucide-react";

interface StatCardProps {
  title: string;
  value: string;
  change: string;
  trend?: "up" | "down";
}

export function StatCard({ title, value, change, trend = "up" }: StatCardProps) {
  return (
    <article className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm transition-colors hover:bg-slate-50 focus-within:ring-2 focus-within:ring-indigo-500 dark:border-slate-800 dark:bg-slate-900 dark:hover:bg-slate-800">
      <header className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
        <TrendingUp className="h-5 w-5 text-indigo-500" aria-hidden />
      </header>
      <p className="mt-4 text-3xl font-bold text-slate-900 dark:text-slate-100">{value}</p>
      <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{change}</p>
    </article>
  );
}
```

### 4.5 Formulare
- Labels über Inputs, Pflichtfelder mit `*`.
- Inputs haben klare Fokus-Indikatoren (`focus:ring-2 focus:ring-indigo-500`).
- Buttons platzieren rechtsbündig in Form-Actions.
- Fehlertexte rot (`text-red-500 text-sm`).

```tsx
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/use-toast";

const schema = z.object({
  projectName: z.string().min(1, "Name ist erforderlich"),
  ownerEmail: z.string().email("Bitte eine gültige E-Mail eingeben"),
});

type FormValues = z.infer<typeof schema>;

export function ProjectForm() {
  const { toast } = useToast();
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  async function onSubmit(values: FormValues) {
    try {
      await saveProject(values);
      toast({
        title: "✅ Einstellungen gespeichert",
        description: "Das Projekt wurde erfolgreich aktualisiert.",
        variant: "success",
      });
    } catch (error) {
      toast({
        title: "❌ Fehler beim Speichern",
        description: "Bitte versuche es erneut.",
        variant: "destructive",
      });
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
      <div className="space-y-2">
        <Label htmlFor="projectName">
          Projektname <span className="text-red-500">*</span>
        </Label>
        <Input
          id="projectName"
          autoComplete="organization"
          placeholder="Neue Harmonie"
          className="focus-visible:ring-2 focus-visible:ring-indigo-500"
          {...register("projectName")}
        />
        {errors.projectName && <p className="text-xs text-red-500">{errors.projectName.message}</p>}
      </div>

      <div className="space-y-2">
        <Label htmlFor="ownerEmail">
          Owner E-Mail <span className="text-red-500">*</span>
        </Label>
        <Input
          id="ownerEmail"
          type="email"
          autoComplete="email"
          placeholder="you@company.com"
          className="focus-visible:ring-2 focus-visible:ring-indigo-500"
          {...register("ownerEmail")}
        />
        {errors.ownerEmail && <p className="text-xs text-red-500">{errors.ownerEmail.message}</p>}
      </div>

      <div className="flex items-center justify-end gap-2">
        <Button type="button" variant="outline">
          Abbrechen
        </Button>
        <Button type="submit" disabled={isSubmitting} className="disabled:opacity-50 disabled:cursor-not-allowed">
          {isSubmitting ? (
            <span className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" /> Speichern
            </span>
          ) : (
            "Speichern"
          )}
        </Button>
      </div>
    </form>
  );
}
```

### 4.6 Buttons
- Primärbutton: Indigo-Hintergrund, weißer Text (`bg-indigo-600 hover:bg-indigo-700 text-white`).
- Sekundärbutton: graue Outlines (`border border-slate-300 bg-white hover:bg-slate-100`).
- Disabled-State: `opacity-50 cursor-not-allowed`.
- Immer `transition-colors duration-200`.

```tsx
import { cn } from "@/lib/utils";
import { ButtonHTMLAttributes } from "react";

const baseStyles = "inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-medium transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-50";

export function PrimaryButton({ className, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={cn(baseStyles, "bg-indigo-600 text-white hover:bg-indigo-700", className)} {...props} />;
}

export function SecondaryButton({ className, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={cn(baseStyles, "border border-slate-300 bg-white text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800", className)} {...props} />;
}
```

### 4.7 Toasts & Notifications
- Radix Toast via shadcn/ui.
- Maximal drei Toasts gleichzeitig sichtbar.
- Farbgebung je Status.

```tsx
import {
  Toast,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
} from "@/components/ui/toast";
import { useToast } from "@/components/ui/use-toast";

export function ExampleToasts() {
  const { toasts } = useToast();

  return (
    <ToastProvider duration={6000} swipeDirection="right">
      {toasts.map(({ id, title, description, action, variant, open, duration, onOpenChange }) => (
        <Toast
          key={id}
          variant={variant}
          open={open}
          duration={duration}
          onOpenChange={onOpenChange}
        >
          <div className="grid gap-1">
            {title && <ToastTitle>{title}</ToastTitle>}
            {description && <ToastDescription>{description}</ToastDescription>}
          </div>
          {action}
          <ToastClose />
        </Toast>
      ))}
      <ToastViewport />
    </ToastProvider>
  );
}
```

Verwende Varianten:
- Erfolg: `variant="success"`, Hintergrund grün (`bg-emerald-500/10 text-emerald-700 dark:text-emerald-200`).
- Fehler: `variant="destructive"`, Hintergrund rot.
- Info: Custom-Variante mit blauem Schema.

## 5. Interaktionen & States
- **Hover:** Hintergrund abdunkeln (`hover:bg-slate-50` bzw. `dark:hover:bg-slate-800`).
- **Focus:** `focus-visible:ring-2 focus-visible:ring-indigo-500` verpflichtend.
- **Loader:** `Loader2` Icon (`lucide-react`) mit `animate-spin` und Größe `h-4 w-4` (Buttons) bzw. `h-6 w-6` (Fullscreen).
- **Disabled:** `opacity-50 cursor-not-allowed`, Interaktionen deaktivieren (`pointer-events-none` falls nötig).

## 6. Responsive Breakpoints
- `sm`: 640px
- `md`: 768px
- `lg`: 1024px
- `xl`: 1280px
- Sidebar wechselt unter `<md` in den Drawer-Modus.

## 7. Icons
- Quelle: `lucide-react`.
- Standardgröße: `h-5 w-5`.
- Primärfarbe text-slate im Light Mode, `text-slate-300` im Dark Mode. Für Statusicons relevante Farbe verwenden.

## 8. Notifications
- Verwende ausschließlich die Toast-Komponente (siehe Abschnitt 4.7).
- Statusfarben: Erfolg (grün), Fehler (rot), Info (blau).
- Maximal drei Toasts gleichzeitig sichtbar (`toasts.slice(0, 3)`).
- Erfolgsnachricht nach Speichern: `"✅ Einstellungen gespeichert"`.
- Fehlerfall: `"❌ Fehler beim Speichern"`.

## 9. Animationen
- Sidebar-Drawer: Slide-in/out mittels Framer Motion (`initial`/`animate`/`exit`).
- Buttons: `transition-colors duration-200` Standard.
- Loader: `animate-spin`.
- Dark-Mode-Umschaltung mit sanftem Übergang (`transition-colors transition-opacity duration-300`).

## 10. UX-Details
- Pflichtfelder mit `*` kennzeichnen und in `aria-label`/`aria-required` widerspiegeln.
- Formulare haben konsistente Titel (`text-lg font-semibold`) und strukturierte Abschnitte.
- Validierungsfehler unmittelbar unter dem Feld anzeigen.
- Erfolgreiches Speichern löst Toast `✅ Einstellungen gespeichert` aus.
- Fehler beim Speichern löst Toast `❌ Fehler beim Speichern` aus und kann ergänzende Beschreibung enthalten.
- Globale Ladezustände nutzen `Loader2` Icon und deaktivieren interaktive Elemente.

Diese Richtlinien sind verpflichtend. Abweichungen müssen vor Implementierung abgestimmt und in diesem Dokument dokumentiert werden.
