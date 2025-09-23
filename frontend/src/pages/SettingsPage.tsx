import { Loader2 } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle
} from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Button } from '../components/ui/button';
import useServiceSettingsForm from '../hooks/useServiceSettingsForm';

const generalFields = [
  { key: 'app.name', label: 'Application name', placeholder: 'Harmony' },
  { key: 'app.language', label: 'Language', placeholder: 'en' },
  { key: 'app.timezone', label: 'Timezone', placeholder: 'UTC' }
] as const;

const notificationFields = [
  { key: 'notifications.email', label: 'Alert email', placeholder: 'alerts@example.com' },
  { key: 'notifications.slackWebhook', label: 'Slack webhook', placeholder: 'https://hooks.slack.com/...' }
] as const;

const SettingsPage = () => {
  const general = useServiceSettingsForm({
    fields: generalFields,
    loadErrorDescription: 'General settings could not be loaded.',
    successTitle: 'General settings saved',
    errorTitle: 'Failed to save general settings'
  });

  const notifications = useServiceSettingsForm({
    fields: notificationFields,
    loadErrorDescription: 'Notification settings could not be loaded.',
    successTitle: 'Notification settings saved',
    errorTitle: 'Failed to save notification settings'
  });

  return (
    <Tabs defaultValue="general">
      <TabsList>
        <TabsTrigger value="general">General</TabsTrigger>
        <TabsTrigger value="notifications">Notifications</TabsTrigger>
      </TabsList>
      <TabsContent value="general">
        <Card>
          <CardHeader>
            <CardTitle>General configuration</CardTitle>
          </CardHeader>
          {general.isLoading ? (
            <CardContent>
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            </CardContent>
          ) : (
            <form onSubmit={general.onSubmit} className="space-y-6">
              <CardContent className="space-y-4">
                {generalFields.map(({ key, label, placeholder }) => (
                  <div key={key} className="space-y-2">
                    <Label htmlFor={key}>{label}</Label>
                    <Input id={key} placeholder={placeholder} {...general.form.register(key)} />
                  </div>
                ))}
              </CardContent>
              <CardFooter className="gap-2">
                <Button type="submit" disabled={general.isSaving}>
                  {general.isSaving ? 'Saving…' : 'Save changes'}
                </Button>
                <Button type="button" variant="outline" onClick={general.handleReset} disabled={general.isSaving}>
                  Reset
                </Button>
              </CardFooter>
            </form>
          )}
        </Card>
      </TabsContent>
      <TabsContent value="notifications">
        <Card>
          <CardHeader>
            <CardTitle>Notification settings</CardTitle>
          </CardHeader>
          {notifications.isLoading ? (
            <CardContent>
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            </CardContent>
          ) : (
            <form onSubmit={notifications.onSubmit} className="space-y-6">
              <CardContent className="space-y-4">
                {notificationFields.map(({ key, label, placeholder }) => (
                  <div key={key} className="space-y-2">
                    <Label htmlFor={key}>{label}</Label>
                    <Input id={key} placeholder={placeholder} {...notifications.form.register(key)} />
                  </div>
                ))}
              </CardContent>
              <CardFooter className="gap-2">
                <Button type="submit" disabled={notifications.isSaving}>
                  {notifications.isSaving ? 'Saving…' : 'Save changes'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={notifications.handleReset}
                  disabled={notifications.isSaving}
                >
                  Reset
                </Button>
              </CardFooter>
            </form>
          )}
        </Card>
      </TabsContent>
    </Tabs>
  );
};

export default SettingsPage;
