import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";

const BeetsPage = () => {
  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Beets</h1>
        <p className="text-sm text-muted-foreground">
          Integration für Beets-Sammlungen. Weitere Funktionen folgen in einem späteren Update.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>In Arbeit</CardTitle>
          <CardDescription>Die Beets-Verwaltung wird aktuell vorbereitet.</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Sobald die API verfügbar ist, erscheinen hier Synchronisationsdetails und Import-Werkzeuge für Beets.
          </p>
        </CardContent>
      </Card>
    </div>
  );
};

export default BeetsPage;
