import React from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from './dialog';
import { Button } from './button';
import { Globe, Database, Zap, Sparkles } from 'lucide-react';
import { getFeatureIcon } from '../../lib/feature-icons';
import { cn } from '@/lib/utils';

const FeatureCard = ({ feature, index }) => {
  const IconComponent = getFeatureIcon(feature);
  
  return (
    <div
      className={cn(
        "group relative overflow-hidden rounded-lg border transition-all duration-300 hover:shadow-lg",
        "bg-slate-50 border-slate-200 hover:border-slate-700 hover:bg-slate-100/80",
        "dark:bg-slate-800/50 dark:border-slate-700 dark:hover:border-slate-600 dark:hover:bg-slate-800/80",
        "animate-in fade-in-0 slide-in-from-bottom-4"
      )}
      style={{ animationDelay: `${index * 100}ms` }}
    >
      <div className="relative flex items-start gap-3 p-4">
        <div className="flex-shrink-0 rounded-full bg-slate-200 dark:bg-slate-700/50 p-2 group-hover:bg-indigo-600 dark:group-hover:bg-indigo-500 transition-all duration-300">
          <IconComponent className="h-4 w-4 text-slate-600 dark:text-slate-300 group-hover:text-white dark:group-hover:text-white transition-all duration-300 ease-in-out group-hover:rotate-12" />
        </div>
        
        <div className="flex-1 min-w-0">
          <h4 className="font-semibold text-slate-900 dark:text-slate-100 text-sm leading-tight mb-1 transition-colors">
            {feature.title}
          </h4>
          <p className="text-slate-600 dark:text-slate-400 text-sm leading-relaxed">
            {feature.description}
          </p>
        </div>
      </div>
    </div>
  );
};

const CategorySection = ({ title, features, icon: Icon }) => (
  <div className="space-y-3">
    <div className="flex items-center gap-2 pb-2 border-b border-slate-200 dark:border-slate-700">
      <Icon className="h-5 w-5 text-indigo-600 dark:text-indigo-400 transition-all duration-300 ease-in-out hover:rotate-[15deg]" />
      <h3 className="font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
    </div>
    
    <div className="space-y-3">
      {features.map((feature, index) => (
        <FeatureCard key={index} feature={feature} index={index} />
      ))}
    </div>
  </div>
);

const VersionBadge = ({ version }) => (
  <div className="inline-flex items-center justify-center min-w-[3rem] h-8 px-2 rounded-full bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 font-semibold text-xs border border-indigo-200 dark:border-indigo-800">
    v{version}
  </div>
);

const VersionSection = ({ versionData, index }) => (
  <div 
    className={cn(
      "space-y-4 p-4 rounded-lg border bg-gradient-to-br transition-all duration-500",
      "from-slate-50/50 to-slate-100/30 border-slate-200",
      "dark:from-slate-800/30 dark:to-slate-900/50 dark:border-slate-700",
      "animate-in fade-in-0 slide-in-from-left-4"
    )}
    style={{ animationDelay: `${index * 150}ms` }}
  >
    <div className="flex items-center gap-3 pb-3 border-b border-slate-200 dark:border-slate-700">
      <VersionBadge version={versionData.version} />
      <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
        Version {versionData.version}
      </h2>
    </div>

    <div className="space-y-4">
      {versionData.changes.frontend?.length > 0 && (
        <CategorySection
          title="Frontend Improvements"
          features={versionData.changes.frontend}
          icon={Globe}
        />
      )}

      {versionData.changes.backend?.length > 0 && (
        <CategorySection
          title="Backend Enhancements"
          features={versionData.changes.backend}
          icon={Database}
        />
      )}

      {versionData.changes.development?.length > 0 && (
        <CategorySection
          title="Development & Infrastructure"
          features={versionData.changes.development}
          icon={Zap}
        />
      )}
    </div>
  </div>
);

const FlatChangesDisplay = ({ changes }) => (
  <>
    {changes.frontend?.length > 0 && (
      <CategorySection
        title="Frontend Improvements"
        features={changes.frontend}
        icon={Globe}
      />
    )}

    {changes.backend?.length > 0 && (
      <CategorySection
        title="Backend Enhancements"
        features={changes.backend}
        icon={Database}
      />
    )}

    {changes.development?.length > 0 && (
      <CategorySection
        title="Development & Infrastructure"
        features={changes.development}
        icon={Zap}
      />
    )}
  </>
);

export function WhatsNewModal({ isOpen, onClose, onDismiss, version, changes, groupedChanges }) {
  const hasGroupedData = groupedChanges?.length > 0;

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-hidden">
        <DialogHeader className="pb-4">
          <div className="flex items-center gap-3">
            <div className="rounded-full bg-gradient-to-br from-indigo-100 to-indigo-200 dark:from-indigo-900/50 dark:to-indigo-800/50 p-2">
              <Sparkles className="h-6 w-6 text-indigo-600 dark:text-indigo-400" />
            </div>
            <div>
              <DialogTitle className="text-xl font-bold text-slate-900 dark:text-slate-100">
                What's New in Portracker {version}
              </DialogTitle>
              <DialogDescription className="text-slate-600 dark:text-slate-400 mt-1">
                Discover the latest features and improvements
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="overflow-y-auto pr-2 -mr-2" style={{ maxHeight: 'calc(80vh - 200px)' }}>
          <div className="space-y-6">
            {hasGroupedData ? (
              groupedChanges.map((versionData, index) => (
                <VersionSection key={versionData.version} versionData={versionData} index={index} />
              ))
            ) : (
              <FlatChangesDisplay changes={changes} />
            )}
          </div>
        </div>

        <div className="flex justify-between pt-4 border-t border-slate-200 dark:border-slate-700">
          <Button
            variant="ghost"
            onClick={() => {
              if (onDismiss) {
                onDismiss();
              }
              onClose();
            }}
            className="text-slate-600 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200"
          >
            Don't show again
          </Button>
          
          <Button
            onClick={onClose}
            className="min-w-[120px] bg-indigo-600 hover:bg-indigo-700 text-white dark:bg-indigo-500 dark:hover:bg-indigo-600 transition-colors duration-200"
          >
            Get Started
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
