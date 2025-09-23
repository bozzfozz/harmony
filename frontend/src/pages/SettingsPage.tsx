import { Loader2 } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import useServiceSettingsForm, { SettingsFieldDefinition } from '../hooks/useServiceSettingsForm';

const SETTINGS_SECTIONS = [
  {
    id: 'spotify',
    label: 'Spotify',
    fields: [
      { key: 'SPOTIFY_CLIENT_ID', label: 'Client ID' },
      { key: 'SPOTIFY_CLIENT_SECRET', label: 'Client Secret' },
      { key: 'SPOTIFY_REDIRECT_URI', label: 'Redirect URI' }
    ]
  },
  {
    id: 'plex',
    label: 'Plex',
    fields: [
      { key: 'PLEX_BASE_URL', label: 'Basis-URL' },
      { key: 'PLEX_TOKEN', label: 'Token' },
      { key: 'PLEX_LIBRARY', label: 'Bibliothek' }
    ]
  },
  {
    id: 'soulseek',
    label: 'Soulseek',
    fields: [
      { key: 'SLSKD_URL', label: 'slskd URL' },
      { key: 'SLSKD_API_KEY', label: 'API Key' }
    ]
  },
  {
    id: 'beets',
    label: 'Beets',
    fields: [
      { key: 'BEETS_LIBRARY_PATH', label: 'Library Pfad' },
      { key: 'BEETS_IMPORT_TARGET', label: 'Import Ziel' }
    ]
  }
] as const;

const SETTINGS_FIELDS: readonly SettingsFieldDefinition[] = SETTINGS_SECTIONS.flatMap(
  (section) => section.fields
);

const SettingsPage = () => {
  const { form, onSubmit, handleReset, isSaving, isLoading } = useServiceSettingsForm({ fields: SETTINGS_FIELDS });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <Tabs defaultValue="spotify">
      <TabsList className="grid grid-cols-2 gap-2 md:w-[480px] md:grid-cols-4">
        {SETTINGS_SECTIONS.map((section) => (
          <TabsTrigger key={section.id} value={section.id}>
            {section.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {SETTINGS_SECTIONS.map((section) => (
        <TabsContent key={section.id} value={section.id}>
          <form onSubmit={onSubmit}>
            <Card>
              <CardHeader>
                <CardTitle>{section.label} Einstellungen</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {section.fields.map((field) => (
                  <div className="grid gap-2" key={field.key}>
                    <Label htmlFor={field.key}>{field.label}</Label>
                    <Input id={field.key} {...form.register(field.key)} placeholder={`Wert für ${field.label}`} />
                  </div>
                ))}
              </CardContent>
              <CardFooter className="justify-end">
                <div className="flex gap-2">
                  <Button type="button" variant="ghost" onClick={handleReset}>
                    Zurücksetzen
                  </Button>
                  <Button type="submit" disabled={isSaving}>
                    {isSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    Speichern
                  </Button>
                </div>
              </CardFooter>
            </Card>
          </form>
        </TabsContent>
      ))}
    </Tabs>
  );
};

export default SettingsPage;
