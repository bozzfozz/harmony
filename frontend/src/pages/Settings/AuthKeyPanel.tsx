import { useMemo, useState } from 'react';
import { Eye, EyeOff, Save, Trash } from 'lucide-react';

import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  Input
} from '../../components/ui/shadcn';
import { Label } from '../../components/ui/label';
import { useToast } from '../../hooks/useToast';
import { LOCAL_STORAGE_KEY } from '../../lib/auth';

export const maskKey = (value: string): string => value.replace(/./gu, '•');

export const getDisplayedKey = (value: string, isRevealed: boolean): string => {
  const trimmed = value.trim();
  if (!trimmed) {
    return 'Kein lokaler Key gespeichert.';
  }
  return isRevealed ? trimmed : maskKey(trimmed);
};

const readLocalKey = (): string => {
  if (typeof window === 'undefined') {
    return '';
  }
  try {
    return window.localStorage.getItem(LOCAL_STORAGE_KEY) ?? '';
  } catch (error) {
    return '';
  }
};

const AuthKeyPanel = () => {
  const { toast } = useToast();
  const [storedKey, setStoredKey] = useState<string>(() => readLocalKey());
  const [inputValue, setInputValue] = useState<string>(() => readLocalKey());
  const [isRevealed, setIsRevealed] = useState(false);

  const hasStoredKey = storedKey.trim().length > 0;

  const displayedKey = useMemo(
    () => getDisplayedKey(storedKey, isRevealed),
    [isRevealed, storedKey]
  );

  const persistKey = (value: string) => {
    if (typeof window === 'undefined') {
      return;
    }
    try {
      if (value) {
        window.localStorage.setItem(LOCAL_STORAGE_KEY, value);
      } else {
        window.localStorage.removeItem(LOCAL_STORAGE_KEY);
      }
    } catch (error) {
      toast({
        title: 'Speichern fehlgeschlagen',
        description: 'Der Schlüssel konnte im aktuellen Browser nicht gespeichert werden.',
        variant: 'destructive'
      });
    }
  };

  const handleSave = () => {
    const trimmed = inputValue.trim();
    persistKey(trimmed);
    setStoredKey(trimmed);
    setIsRevealed(false);
    toast({
      title: trimmed ? 'API-Key gespeichert' : 'API-Key entfernt',
      description: trimmed
        ? 'Lokale Requests verwenden nun den hinterlegten Key.'
        : 'Lokale Requests greifen wieder auf Laufzeit- oder ENV-Keys zurück.'
    });
  };

  const handleClear = () => {
    persistKey('');
    setStoredKey('');
    setInputValue('');
    setIsRevealed(false);
    toast({
      title: 'API-Key entfernt',
      description: 'Der lokale Key wurde gelöscht.'
    });
  };

  const toggleReveal = () => {
    setIsRevealed((previous) => !previous);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>API-Key</CardTitle>
        <CardDescription>
          Verwaltet den lokalen API-Key. Priorität: <code>VITE_API_KEY</code> →{' '}
          <code>localStorage</code> → Laufzeitkonfiguration.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="auth-key-input">Neuer Key</Label>
          <Input
            id="auth-key-input"
            autoComplete="off"
            value={inputValue}
            onChange={(event) => setInputValue(event.target.value)}
            placeholder="API-Key hier eingeben"
          />
          <p className="text-xs text-muted-foreground">
            Der Schlüssel wird nur im aktuellen Browser gespeichert und niemals protokolliert.
          </p>
        </div>
        <div className="flex flex-col gap-2 rounded-lg border p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Gespeicherter Key</p>
              <p data-testid="stored-key-value" className="text-sm text-muted-foreground break-all">
                {displayedKey}
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={toggleReveal}
                disabled={!hasStoredKey}
              >
                {isRevealed ? (
                  <>
                    <EyeOff className="mr-2 h-4 w-4" /> Verbergen
                  </>
                ) : (
                  <>
                    <Eye className="mr-2 h-4 w-4" /> Anzeigen
                  </>
                )}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleClear}
                disabled={!hasStoredKey}
              >
                <Trash className="mr-2 h-4 w-4" /> Löschen
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
      <CardFooter className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Ohne lokalen Key fällt das Frontend automatisch auf Laufzeitwerte zurück.
        </p>
        <Button type="button" onClick={handleSave}>
          <Save className="mr-2 h-4 w-4" /> Speichern
        </Button>
      </CardFooter>
    </Card>
  );
};

export default AuthKeyPanel;
