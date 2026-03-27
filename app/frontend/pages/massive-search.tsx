import { Building2, CheckCircle2, Database, Globe, Hash, Instagram, Linkedin, Loader2, Mail, MapPin, Search, TrendingUp, XCircle, Zap } from 'lucide-react';
import { useRouter } from 'next/router';
import { useEffect, useState } from 'react';
import api from '../lib/api';
import InfoBox from '../components/InfoBox';
import Tooltip from '../components/Tooltip';

interface SearchMethod {
  id: string;
  name: string;
  icon: any;
  description: string;
  rateLimit: string;
  enabled: boolean;
}

interface NicheWithCategory {
  id: string;
  name: string;
  category: string;
  selected: boolean;
}

const REGIONS = [
  { id: 'grande_vitoria_es', name: 'Grande Vitória-ES', cities: ['Vitória', 'Vila Velha', 'Serra', 'Cariacica', 'Viana', 'Guarapari', 'Fundão'] },
  { id: 'grande_sp', name: 'Grande São Paulo-SP', cities: ['São Paulo', 'Guarulhos', 'Osasco', 'Santo André'] },
  { id: 'grande_rj', name: 'Grande Rio de Janeiro-RJ', cities: ['Rio de Janeiro', 'Niterói', 'Duque de Caxias'] },
  { id: 'grande_bh', name: 'Grande Belo Horizonte-MG', cities: ['Belo Horizonte', 'Contagem', 'Betim'] },
];

export default function MassiveSearch() {
  const router = useRouter();
  const [niches, setNiches] = useState<NicheWithCategory[]>([]);
  const [loadingNiches, setLoadingNiches] = useState(true);
  const [nicheWarning, setNicheWarning] = useState('');
  const [customNiche, setCustomNiche] = useState('');

  // Load niches from DB catalog
  useEffect(() => {
    api.get('/api/niches?active=true')
      .then(res => {
        const grouped: Record<string, { id: number; name: string }[]> = res.data?.niches || {};
        const flat: NicheWithCategory[] = Object.entries(grouped).flatMap(
          ([category, items]) => items.map(n => ({
            id: String(n.id),
            name: n.name,
            category,
            selected: false,
          }))
        );
        setNiches(flat);
      })
      .catch(() => {})
      .finally(() => setLoadingNiches(false));
  }, []);

  // Load ES cities from regions table
  useEffect(() => {
    api.get('/api/admin/regions')
      .then(res => setEsCities((res.data.regions || []).filter((r: any) => r.active)))
      .catch(() => setEsCities([]));
  }, []);

  const [selectedRegion, setSelectedRegion] = useState('grande_vitoria_es');
  const [esCities, setEsCities] = useState<Array<{id: number; name: string; city: string}>>([]);
  const [selectedCity, setSelectedCity] = useState<string>('');
  const [citySearch, setCitySearch] = useState<string>('');
  const [maxPages, setMaxPages] = useState(2);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const [methods, setMethods] = useState<SearchMethod[]>([
    {
      id: 'api_enrichment',
      name: 'API Enrichment',
      icon: Database,
      description: 'Hunter.io + Snov.io para encontrar emails',
      rateLimit: '3 buscas/hora',
      enabled: true,
    },
    {
      id: 'search_engines',
      name: 'Motores de Busca',
      icon: Search,
      description: 'DuckDuckGo + Bing para scrapar resultados',
      rateLimit: '3 buscas/hora',
      enabled: true,
    },
    {
      id: 'google_maps',
      name: 'Google Maps',
      icon: MapPin,
      description: 'Playwright scraping de negócios locais',
      rateLimit: '5 buscas/hora',
      enabled: true,
    },
    {
      id: 'instagram',
      name: 'Instagram Business',
      icon: Instagram,
      description: 'Perfis empresariais do Instagram',
      rateLimit: '3 perfis/hora',
      enabled: false,
    },
    {
      id: 'linkedin',
      name: 'LinkedIn Companies',
      icon: Linkedin,
      description: 'Empresas no LinkedIn',
      rateLimit: '2 empresas/hora',
      enabled: false,
    },
    {
      id: 'local_business_data',
      name: 'Local Business Data',
      icon: Building2,
      description: 'Google Maps via API (RapidAPI) — sem browser, dados estruturados',
      rateLimit: '500 leads/mês (free)',
      enabled: true,
    },
    {
      id: 'google_email_harvest',
      name: 'Google Email Harvest',
      icon: Mail,
      description: 'Busca emails no Google com dorks + visita os top sites para extrair contatos',
      rateLimit: '3 nichos × 3 cidades',
      enabled: true,
    },
    {
      id: 'website_email_crawler',
      name: 'Website Email Crawler',
      icon: Globe,
      description: 'Busca sites via DuckDuckGo e faz deep crawl em /contato, /sobre para extrair emails',
      rateLimit: '5 nichos × 5 cidades',
      enabled: true,
    },
    {
      id: 'cnpj_open',
      name: 'CNPJ Open (Receita Federal)',
      icon: Hash,
      description: 'Busca CNPJs em diretórios e enriquece via API OpenCNPJ — email e telefone oficiais',
      rateLimit: 'Grátis (50 req/s)',
      enabled: true,
    },
    {
      id: 'serper_google',
      name: 'Serper Google API',
      icon: Search,
      description: 'Google Search API (Serper.dev) — resultados estruturados com emails nos snippets',
      rateLimit: '2500 buscas/mês (free)',
      enabled: false,
    },
    {
      id: 'apify_maps',
      name: 'Apify Google Maps',
      icon: MapPin,
      description: 'Apify actor para Google Maps com extração automática de emails dos sites',
      rateLimit: '~1250 leads/mês ($5 free)',
      enabled: false,
    },
  ]);

  const toggleNiche = (id: string) => {
    setNiches(niches.map(n => n.id === id ? { ...n, selected: !n.selected } : n));
  };

  const addCustomNiche = async () => {
    const name = customNiche.trim();
    if (!name) return;
    // Prevent duplicates
    if (niches.some(n => n.name.toLowerCase() === name.toLowerCase())) {
      setNiches(prev => prev.map(n =>
        n.name.toLowerCase() === name.toLowerCase() ? { ...n, selected: true } : n
      ));
      setCustomNiche('');
      return;
    }

    const newNiche: NicheWithCategory = { id: `custom_${Date.now()}`, name, category: 'Personalizado', selected: true };
    setNiches(prev => [...prev, newNiche]);
    setCustomNiche('');

    // Also persist to DB
    try {
      await api.post('/api/niches/custom', { name });
    } catch {
      // niche already added to local state
    }
  };

  const selectAll = () => {
    const allSelected = niches.map(n => ({ ...n, selected: true }));
    const selectedCount = allSelected.length;
    if (selectedCount > 50) {
      setNicheWarning('Máximo de 50 nichos por busca para não sobrecarregar o servidor.');
    } else {
      setNicheWarning('');
    }
    setNiches(allSelected);
  };

  const clearAll = () => {
    setNicheWarning('');
    setNiches(niches.map(n => ({ ...n, selected: false })));
  };

  const toggleMethod = (id: string) => {
    setMethods(methods.map(m => m.id === id ? { ...m, enabled: !m.enabled } : m));
  };

  const getSelectedNiches = () => {
    return niches.filter(n => n.selected).map(n => n.name);
  };

  const getEnabledMethods = () => {
    return methods.filter(m => m.enabled).map(m => m.id);
  };

  const handleStartMassiveSearch = async () => {
    const selectedNiches = getSelectedNiches();
    const enabledMethods = getEnabledMethods();

    if (selectedNiches.length === 0) {
      setError('Selecione pelo menos um nicho');
      return;
    }

    if (enabledMethods.length === 0) {
      setError('Selecione pelo menos um método de busca');
      return;
    }

    setLoading(true);
    setError('');
    setSuccess('');

    try {
      const payload: any = {
        niches: selectedNiches,
        methods: enabledMethods,
        max_pages: maxPages,
      };

      if (selectedRegion === 'es_city' && selectedCity) {
        payload.city = selectedCity;
        payload.state = 'ES';
      } else {
        payload.region = selectedRegion;
      }

      const response = await api.post('/api/search/massive', payload);

      const { batch_id } = response.data;
      setSuccess(`Busca massiva iniciada! ${response.data.total_jobs} jobs em execução.`);

      // Redirect to batch progress page after 2 seconds
      setTimeout(() => {
        router.push(`/batch/${batch_id}`);
      }, 2000);
    } catch (err: any) {
      setError(err.response?.data?.error || 'Erro ao iniciar busca massiva');
    } finally {
      setLoading(false);
    }
  };

  const selectedRegionData = REGIONS.find(r => r.id === selectedRegion);
  const selectedNichesCount = niches.filter(n => n.selected).length;
  const enabledMethodsCount = methods.filter(m => m.enabled).length;
  const estimatedJobs = selectedNichesCount * enabledMethodsCount * (selectedRegionData?.cities.length || 1);

  return (
    <div className="max-w-7xl mx-auto py-8 px-4">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-3">
            <div className="p-3 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl">
              <Zap className="h-8 w-8 text-white" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Busca Massiva</h1>
              <p className="text-gray-600 dark:text-gray-400">Extraia leads usando múltiplos métodos simultaneamente</p>
            </div>
          </div>
        </div>

        {/* InfoBox */}
        <div className="mb-6">
          <InfoBox
            storageKey="massive_search"
            title="Busca Massiva — Como funciona?"
            description="Esta ferramenta dispara varios metodos de extracao ao mesmo tempo para varios nichos e cidades simultaneamente. E a forma mais rapida de capturar muitos leads de uma vez."
            steps={[
              'Passo 1: Escolha os tipos de negocio que deseja prospectar',
              'Passo 2: Selecione a regiao (conjunto de cidades)',
              'Passo 3: Marque quais metodos de busca ativar (DuckDuckGo, Google Maps, etc.)',
              'Clique em Iniciar — voce sera redirecionado para o progresso em tempo real',
            ]}
          />
        </div>

        {/* Alert Messages */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-start gap-3">
            <XCircle className="h-5 w-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
            <p className="text-red-800 dark:text-red-300">{error}</p>
          </div>
        )}

        {success && (
          <div className="mb-6 p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg flex items-start gap-3">
            <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400 flex-shrink-0 mt-0.5" />
            <p className="text-green-800 dark:text-green-300">{success}</p>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column: Configuration */}
          <div className="lg:col-span-2 space-y-6">
            {/* Step 1: Select Niches */}
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
              {/* Step 1 header row */}
              <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center text-blue-600 dark:text-blue-400 font-bold">
                    1
                  </div>
                  <div>
                    <h2 className="text-xl font-bold text-gray-900 dark:text-white">Selecione os Nichos</h2>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {niches.filter(n => n.selected).length} de {niches.length} selecionados
                    </p>
                  </div>
                  <Tooltip text="Nicho = tipo de negocio. Escolha um ou mais. Voce pode adicionar um nicho personalizado se o seu segmento nao estiver na lista." position="right" />
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={selectAll}
                    className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
                  >
                    Selecionar todos
                  </button>
                  <button
                    onClick={clearAll}
                    className="px-3 py-1.5 text-sm bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 rounded-lg transition-colors"
                  >
                    Limpar seleção
                  </button>
                </div>
              </div>

              {nicheWarning && (
                <div className="mb-3 p-2 bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-400 rounded text-sm">
                  {nicheWarning}
                </div>
              )}

              {/* Grouped niche display */}
              {loadingNiches ? (
                <p className="text-sm text-gray-500 dark:text-gray-400 py-4">Carregando nichos...</p>
              ) : niches.length === 0 ? (
                <p className="text-sm text-yellow-600 dark:text-yellow-400 py-4">
                  Nenhum nicho cadastrado — contate o admin.
                </p>
              ) : (
                <div className="space-y-4 mb-4">
                  {Array.from(new Set(niches.map(n => n.category))).map(category => (
                    <div key={category}>
                      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
                        {category}
                      </h3>
                      <div className="flex flex-wrap gap-2">
                        {niches.filter(n => n.category === category).map(niche => (
                          <button
                            key={niche.id}
                            onClick={() => {
                              const newNiches = niches.map(n => n.id === niche.id ? { ...n, selected: !n.selected } : n);
                              setNiches(newNiches);
                              const selectedCount = newNiches.filter(n => n.selected).length;
                              if (selectedCount > 50) {
                                setNicheWarning('Máximo de 50 nichos por busca para não sobrecarregar o servidor.');
                              } else {
                                setNicheWarning('');
                              }
                            }}
                            className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                              niche.selected
                                ? 'bg-blue-600 text-white'
                                : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                            }`}
                          >
                            {niche.name}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Custom Niche Input */}
              <div className="flex gap-2">
                <input
                  type="text"
                  value={customNiche}
                  onChange={(e) => setCustomNiche(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && addCustomNiche()}
                  placeholder="Adicionar nicho personalizado..."
                  className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                <button
                  onClick={addCustomNiche}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors"
                >
                  Adicionar
                </button>
              </div>
            </div>

            {/* Step 2: Select Region */}
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center text-blue-600 dark:text-blue-400 font-bold">
                  2
                </div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">Selecione a Região</h2>
                <Tooltip text="A regiao define quais cidades serao pesquisadas. O sistema busca cada nicho em cada cidade da regiao selecionada." position="right" />
              </div>

              <div className="space-y-3">
                {REGIONS.map((region) => (
                  <button
                    key={region.id}
                    onClick={() => setSelectedRegion(region.id)}
                    className={`w-full p-4 rounded-lg border-2 transition-all text-left ${
                      selectedRegion === region.id
                        ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                        : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <MapPin className={`h-5 w-5 flex-shrink-0 mt-0.5 ${selectedRegion === region.id ? 'text-blue-600 dark:text-blue-400' : 'text-gray-400'}`} />
                      <div className="flex-1">
                        <h3 className={`font-bold mb-1 ${selectedRegion === region.id ? 'text-blue-700 dark:text-blue-300' : 'text-gray-900 dark:text-white'}`}>
                          {region.name}
                        </h3>
                        <p className="text-sm text-gray-600 dark:text-gray-400">
                          {region.cities.join(', ')}
                        </p>
                      </div>
                      {selectedRegion === region.id && (
                        <CheckCircle2 className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                      )}
                    </div>
                  </button>
                ))}

                {/* ES individual city option */}
                <button
                  onClick={() => { setSelectedRegion('es_city'); setSelectedCity(''); }}
                  className={`w-full p-4 rounded-lg border-2 transition-all text-left ${
                    selectedRegion === 'es_city'
                      ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                      : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <MapPin className={`h-5 w-5 flex-shrink-0 mt-0.5 ${selectedRegion === 'es_city' ? 'text-blue-600 dark:text-blue-400' : 'text-gray-400'}`} />
                    <div className="flex-1">
                      <h3 className={`font-bold mb-1 ${selectedRegion === 'es_city' ? 'text-blue-700 dark:text-blue-300' : 'text-gray-900 dark:text-white'}`}>
                        Cidade específica do ES
                      </h3>
                      <p className="text-sm text-gray-600 dark:text-gray-400">
                        {esCities.length} cidades disponíveis
                      </p>
                    </div>
                    {selectedRegion === 'es_city' && (
                      <CheckCircle2 className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                    )}
                  </div>
                </button>

                {selectedRegion === 'es_city' && (
                  <div className="mt-3 pl-1">
                    <input
                      type="text"
                      placeholder="Buscar cidade..."
                      value={citySearch}
                      onChange={e => setCitySearch(e.target.value)}
                      className="w-full bg-gray-100 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 mb-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                    <select
                      value={selectedCity}
                      onChange={e => setSelectedCity(e.target.value)}
                      size={6}
                      className="w-full bg-gray-100 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm text-gray-900 dark:text-white"
                    >
                      <option value="">— Selecione uma cidade —</option>
                      {esCities
                        .filter(c => c.name.toLowerCase().includes(citySearch.toLowerCase()))
                        .map(c => (
                          <option key={c.id} value={c.city}>{c.name}</option>
                        ))}
                    </select>
                    {selectedCity && (
                      <p className="text-xs text-green-600 dark:text-green-400 mt-1">Cidade selecionada: {selectedCity}</p>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Step 3: Select Methods */}
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center text-blue-600 dark:text-blue-400 font-bold">
                  3
                </div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">Métodos de Extração</h2>
                <Tooltip text="Cada metodo usa uma fonte diferente. Ative todos para capturar mais leads. Desative metodos que nao deseja usar (ex: Instagram requer conta configurada)." position="right" />
              </div>

              <div className="space-y-3">
                {methods.map((method) => {
                  const Icon = method.icon;
                  return (
                    <button
                      key={method.id}
                      onClick={() => toggleMethod(method.id)}
                      className={`w-full p-4 rounded-lg border-2 transition-all text-left ${
                        method.enabled
                          ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                          : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <Icon className={`h-5 w-5 flex-shrink-0 mt-0.5 ${method.enabled ? 'text-blue-600 dark:text-blue-400' : 'text-gray-400'}`} />
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <h3 className={`font-bold ${method.enabled ? 'text-blue-700 dark:text-blue-300' : 'text-gray-900 dark:text-white'}`}>
                              {method.name}
                            </h3>
                            <span className="text-xs px-2 py-0.5 bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400 rounded">
                              {method.rateLimit}
                            </span>
                          </div>
                          <p className="text-sm text-gray-600 dark:text-gray-400">{method.description}</p>
                        </div>
                        {method.enabled && (
                          <CheckCircle2 className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Advanced Options */}
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
              <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-4">Opções Avançadas</h2>

              <div>
                <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Páginas por Busca: {maxPages}
                  <Tooltip text="Quantas paginas de resultados visitar por nicho+cidade. 1 = mais rapido, menos leads. 3 = mais lento, mais leads." />
                </label>
                <input
                  type="range"
                  min="1"
                  max="3"
                  value={maxPages}
                  onChange={(e) => setMaxPages(parseInt(e.target.value))}
                  className="w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-lg appearance-none cursor-pointer accent-blue-600"
                />
                <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mt-1">
                  <span>Rápido (1)</span>
                  <span>Médio (2)</span>
                  <span>Completo (3)</span>
                </div>
              </div>
            </div>
          </div>

          {/* Right Column: Summary & Action */}
          <div className="space-y-6">
            {/* Summary Card */}
            <div className="bg-gradient-to-br from-blue-600 to-purple-600 rounded-xl shadow-lg p-6 text-white sticky top-4">
              <div className="flex items-center gap-2 mb-4">
                <TrendingUp className="h-6 w-6" />
                <h2 className="text-xl font-bold">Resumo da Busca</h2>
              </div>

              <div className="space-y-4">
                <div>
                  <p className="text-blue-100 text-sm mb-1">Nichos Selecionados</p>
                  <p className="text-2xl font-bold">{selectedNichesCount}</p>
                </div>

                <div>
                  <p className="text-blue-100 text-sm mb-1">Métodos Ativos</p>
                  <p className="text-2xl font-bold">{enabledMethodsCount}</p>
                </div>

                <div>
                  <p className="text-blue-100 text-sm mb-1">Cidades na Região</p>
                  <p className="text-2xl font-bold">{selectedRegionData?.cities.length || 0}</p>
                </div>

                <div className="pt-4 border-t border-blue-400/30">
                  <p className="flex items-center gap-1 text-blue-100 text-sm mb-1">
                    Jobs Estimados
                    <span className="inline-flex">
                      <Tooltip text="Total de combinacoes: nichos x metodos x cidades. Cada job e executado em paralelo." position="left" />
                    </span>
                  </p>
                  <p className="text-3xl font-bold">{estimatedJobs}</p>
                </div>

                <button
                  onClick={handleStartMassiveSearch}
                  disabled={loading || selectedNichesCount === 0 || enabledMethodsCount === 0 || (selectedRegion === 'es_city' && !selectedCity)}
                  className="w-full mt-6 px-6 py-4 bg-white text-blue-600 rounded-lg font-bold text-lg hover:bg-blue-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  {loading ? (
                    <>
                      <Loader2 className="h-5 w-5 animate-spin" />
                      Iniciando...
                    </>
                  ) : (
                    <>
                      <Zap className="h-5 w-5" />
                      Iniciar Busca Massiva
                    </>
                  )}
                </button>

                <p className="text-xs text-blue-100 text-center mt-4">
                  Rate limit: 1 busca massiva por hora
                </p>
              </div>
            </div>

            {/* Info Card */}
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
              <h3 className="font-bold text-gray-900 dark:text-white mb-3">ℹ️ Como funciona?</h3>
              <ul className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
                <li className="flex items-start gap-2">
                  <span className="text-blue-600 dark:text-blue-400">•</span>
                  <span>Múltiplos métodos executam simultaneamente</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-blue-600 dark:text-blue-400">•</span>
                  <span>Resultados consolidados em um único batch</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-blue-600 dark:text-blue-400">•</span>
                  <span>Deduplicação automática de leads</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-blue-600 dark:text-blue-400">•</span>
                  <span>Progresso em tempo real por método</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
  );
}
