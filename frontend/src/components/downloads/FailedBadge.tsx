import { useEffect } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '../ui/shadcn';
import { useDownloadStats } from '../../api/services/downloads';

interface FailedBadgeProps {
  isActive: boolean;
  isSelected?: boolean;
  onSelect: () => void;
  onCountChange?: (count: number) => void;
}

const FailedBadge = ({ isActive, isSelected = false, onSelect, onCountChange }: FailedBadgeProps) => {
  const { data, isLoading } = useDownloadStats({ enabled: isActive });
  const failed = data?.failed ?? 0;

  useEffect(() => {
    onCountChange?.(failed);
  }, [failed, onCountChange]);

  const highlight = failed > 0 || isSelected;
  const label = `Fehlgeschlagen: ${failed}`;

  return (
    <Button
      type="button"
      size="sm"
      variant={isSelected ? 'destructive' : 'outline'}
      onClick={onSelect}
      disabled={isLoading}
      aria-pressed={isSelected}
      className={`flex items-center gap-2 ${highlight ? 'border-destructive/40 text-destructive hover:bg-destructive/10' : 'text-muted-foreground'}`}
      aria-label={label}
    >
      {isLoading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
      <span>{label}</span>
    </Button>
  );
};

export default FailedBadge;
