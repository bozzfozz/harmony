import { useEffect, useMemo } from 'react';
import { useForm, UseFormReturn } from 'react-hook-form';
import { useMutation, useQuery, useQueryClient } from '../lib/query';
import { fetchSettings, updateSettings } from '../lib/api';
import { useToast } from './useToast';

export interface SettingsFieldDefinition {
  key: string;
  label: string;
  placeholder?: string;
}

export interface UseServiceSettingsFormOptions {
  fields: readonly SettingsFieldDefinition[];
  loadErrorDescription?: string;
  successTitle?: string;
  errorTitle?: string;
}

type SettingsFormValues = Record<string, string>;
type SubmitHandler = ReturnType<UseFormReturn<SettingsFormValues>['handleSubmit']>;

export interface UseServiceSettingsFormResult {
  form: UseFormReturn<SettingsFormValues>;
  onSubmit: SubmitHandler;
  handleReset: () => void;
  isSaving: boolean;
  isLoading: boolean;
}

const useServiceSettingsForm = ({
  fields,
  loadErrorDescription = 'Einstellungen konnten nicht geladen werden.',
  successTitle = '✅ Einstellungen gespeichert',
  errorTitle = '❌ Fehler beim Speichern'
}: UseServiceSettingsFormOptions): UseServiceSettingsFormResult => {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
    refetchInterval: 30000,
    onError: () =>
      toast({
        title: '❌ Fehler beim Laden',
        description: loadErrorDescription,
        variant: 'destructive'
      })
  });

  const defaultValues = useMemo(() => {
    const settings = settingsQuery.data?.settings ?? {};
    return fields.reduce<SettingsFormValues>((accumulator, field) => {
      accumulator[field.key] = settings[field.key] ?? '';
      return accumulator;
    }, {});
  }, [fields, settingsQuery.data?.settings]);

  const form = useForm<SettingsFormValues>({ defaultValues });

  useEffect(() => {
    form.reset(defaultValues);
  }, [defaultValues, form]);

  const mutation = useMutation({
    mutationFn: async (values: SettingsFormValues) => {
      const settings = settingsQuery.data?.settings ?? {};
      const updates = Object.entries(values).filter(([key, value]) => (settings[key] ?? '') !== value);
      if (updates.length === 0) {
        return;
      }
      await updateSettings(
        updates.map(([key, value]) => ({
          key,
          value: value.trim() === '' ? null : value
        }))
      );
    },
    onSuccess: () => {
      toast({ title: successTitle });
      queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
    onError: () => toast({ title: errorTitle, variant: 'destructive' })
  });

  const onSubmit = form.handleSubmit((values) => mutation.mutate(values));
  const handleReset = () => form.reset(defaultValues);

  return {
    form,
    onSubmit,
    handleReset,
    isSaving: mutation.isPending,
    isLoading: settingsQuery.isLoading
  };
};

export default useServiceSettingsForm;
