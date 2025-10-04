const MatchingPage = () => (
  <section className="space-y-6">
    <header className="space-y-2">
      <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Matching</h1>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Gleiche neu importierte Titel automatisch mit deiner Bibliothek und externen Diensten ab, um Duplikate und
        Metadaten-Konflikte zu vermeiden.
      </p>
    </header>
    <div className="rounded-xl border border-dashed border-slate-300 bg-white/80 p-6 text-sm text-slate-500 shadow-sm dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-300">
      Das Matching-Dashboard zeigt demnächst den Abgleichsstatus, vorgeschlagene Zuordnungen und Integrationen mit Spotify
      oder lokalen Tags.
    </div>
  </section>
);

export default MatchingPage;
