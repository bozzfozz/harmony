# Bandit Offline

Dieses Paket stellt einen leichtgewichtigen, offline-fähigen Security-Scanner zur Verfügung, der eine Teilmenge der Bandit-CLI
nachbildet. Er prüft Python-Quelltexte auf verbreitete Hochrisiko-Konstrukte (`eval`, `exec`, unsicheres `yaml.load`,
`pickle`-Deserialisierung und Shell-Aufrufe in `subprocess`). Die CLI ist kompatibel zu den im Harmony-Repository verwendeten
Aufrufen (`python scripts/bandit.py -c .bandit -r app`).

Die Implementierung vermeidet externe Abhängigkeiten, sodass lokale und CI-Umgebungen ohne Internetzugriff Security-Scans
durchführen können. Schweregrad- und Vertrauensebenen orientieren sich an Bandit; Ergebnisse übertreffen die in `.bandit`
konfigurierten Schwellenwerte führen zu einem Exit-Code ungleich Null.
