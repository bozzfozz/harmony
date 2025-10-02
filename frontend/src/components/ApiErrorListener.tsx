import { useEffect } from 'react';
import { subscribeToApiErrors } from '../api/client';
import { useToast } from '../hooks/useToast';

const ApiErrorListener = () => {
  const { toast } = useToast();

  useEffect(() => {
    const unsubscribe = subscribeToApiErrors(({ error }) => {
      if (error.handled) {
        return;
      }
      if (!error.status || [401, 403, 503].includes(error.status)) {
        if (error.status === 503) {
          toast({
            title: '❌ Zugangsdaten erforderlich',
            description: error.message || 'Bitte hinterlegen Sie gültige Zugangsdaten in den Einstellungen.',
            variant: 'destructive'
          });
          error.markHandled();
          return;
        }
        if (error.status === 401 || error.status === 403) {
          toast({
            title: 'Authentifizierung erforderlich',
            description: 'Bitte überprüfen Sie die Zugangsdaten in den Einstellungen.',
            variant: 'destructive'
          });
          error.markHandled();
          return;
        }
        toast({
          title: '❌ Anfrage fehlgeschlagen',
          description: error.message || 'Der Server hat nicht geantwortet.',
          variant: 'destructive'
        });
        error.markHandled();
      }
    });

    return unsubscribe;
  }, [toast]);

  return null;
};

export default ApiErrorListener;
