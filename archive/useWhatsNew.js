import { useState, useCallback, useEffect } from 'react';
import {
  parseChangelog,
  getNewVersions,
  setLastSeenVersion,
  combineVersionChanges,
  groupVersionChanges,
  compareVersions
} from '../whats-new';
import Logger from '../logger';

const logger = new Logger('useWhatsNew');

export function useWhatsNew() {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [whatsNewData, setWhatsNewData] = useState({});
  const [newVersions, setNewVersions] = useState([]);
  const [currentVersion, setCurrentVersion] = useState(null);
  const [isDismissed, setIsDismissed] = useState(() => {
    try {
      return localStorage.getItem('portracker_whats_new_dismissed') === 'true';
    } catch {
      return false;
    }
  });
  const [hasNewFeaturesToShow, setHasNewFeaturesToShow] = useState(false);

  const shouldShowButton = hasNewFeaturesToShow && !isDismissed;

  const handleClose = useCallback(() => {
    setIsModalOpen(false);
  }, []);

  const handleShow = useCallback(() => {
    setIsModalOpen(true);
    
    const hasExistingData = newVersions.length > 0 && whatsNewData[newVersions[0]];
    
    if (!hasExistingData && currentVersion) {
      const testChanges = {
        frontend: [
          { title: 'Container Details Drawer', description: 'New slide-out panel to show detailed information for Docker containers including stats, labels, mounts, and environment variables' },
          { title: 'Internal Port Display', description: 'UI now correctly shows and differentiates internal-only ports from published ports with health status monitoring' },
          { title: 'Global Search', description: 'Search bar now includes an option to search across all servers simultaneously' },
          { title: "What's New Modal", description: 'Automatic notification system to stay updated with new features when opening new versions' }
        ],
        backend: [
          { title: 'Collector Caching', description: 'Added caching mechanism to all data collectors to reduce duplicate requests and improve data refresh speed' }
        ]
      };
      setWhatsNewData(prev => ({ ...prev, [currentVersion]: testChanges }));
      setNewVersions([currentVersion]);
    }
  }, [whatsNewData, newVersions, currentVersion]);

  const handleDismiss = useCallback(() => {
    try {
      setIsDismissed(true);
      setHasNewFeaturesToShow(false);
      localStorage.setItem('portracker_whats_new_dismissed', 'true');
      if (newVersions.length > 0) {
        setLastSeenVersion(newVersions[0]);
      }
    } catch (error) {
      logger.warn('Failed to dismiss What\'s New:', error);
    }
  }, [newVersions]);

  useEffect(() => {
    const initializeWhatsNew = async () => {
      try {
        const versionResponse = await fetch('/api/version');
        if (!versionResponse.ok) return;
        
        const versionData = await versionResponse.json();
        if (!versionData?.version) return;
        
        setCurrentVersion(versionData.version);
        
        const changelogResponse = await fetch('/api/changelog');
        if (!changelogResponse.ok) return;
        
        const changelogData = await changelogResponse.json();
        const changelogText = changelogData.content;
        const parsedVersions = parseChangelog(changelogText);
        
        if (Object.keys(parsedVersions).length === 0) return;
        
        const urlParams = new URLSearchParams(window.location.search);
        const debugMode = urlParams.get('whatsnew') === '1';
        
        if (debugMode) {
          logger.debug('Debug mode: forcing What\'s New display');
          setWhatsNewData(parsedVersions);
          setNewVersions(Object.keys(parsedVersions).sort((a, b) => compareVersions(b, a)));
          setHasNewFeaturesToShow(true);
          setIsDismissed(false);
          setIsModalOpen(true);
          return;
        }
        
        const lastSeenVersion = localStorage.getItem('portracker_last_seen_version');
        let newVersionsList;
        
        logger.debug('What\'s New initialization:', {
          currentVersion: versionData.version,
          lastSeenVersion,
          isDismissed,
          parsedVersionsCount: Object.keys(parsedVersions).length
        });
        
        if (parsedVersions) {
          newVersionsList = getNewVersions(parsedVersions, lastSeenVersion);
          
          logger.debug('New versions found:', newVersionsList);
          
          if (newVersionsList.length > 0 && lastSeenVersion) {
            const hasNewerVersion = compareVersions(newVersionsList[0], lastSeenVersion) > 0;
            if (hasNewerVersion) {
              setIsDismissed(false);
              try {
                localStorage.removeItem('portracker_whats_new_dismissed');
              } catch (error) {
                void error;
              }
            }
          }
          
          if (newVersionsList.length > 0) {
            setWhatsNewData(parsedVersions);
            setNewVersions(newVersionsList);
            setHasNewFeaturesToShow(true);
            
            logger.debug('Should show modal:', {
              newVersionsCount: newVersionsList.length,
              isDismissed
            });
            
            if (!isDismissed) {
              logger.debug('Opening What\'s New modal');
              setIsModalOpen(true);
            }
          }
        }
      } catch (error) {
        logger.error('Failed to initialize What\'s New:', error);
      }
    };

    initializeWhatsNew();
  }, [isDismissed]);

  const getModalProps = () => {
    const version = newVersions.length > 1 
      ? `${newVersions[newVersions.length - 1]} - ${newVersions[0]}` 
      : (newVersions.length > 0 ? newVersions[0] : currentVersion);
    
    const changes = newVersions.length > 0 
      ? combineVersionChanges(whatsNewData, newVersions)
      : whatsNewData[currentVersion] || {};
    
    const groupedChanges = newVersions.length > 0 
      ? groupVersionChanges(whatsNewData, newVersions)
      : null;

    const props = {
      isOpen: isModalOpen,
      onClose: handleClose,
      onDismiss: handleDismiss,
      version,
      changes,
      groupedChanges
    };

    return props;
  };

  return {
    shouldShowButton,
    handleShow,
    getModalProps
  };
}
