import { CheckCircle2, Database, Instagram, Linkedin, Loader2, MapPin, Search, TrendingUp, XCircle, Zap } from 'lucide-react';
import { useRouter } from 'next/router';
import { useState } from 'react';
import Layout from '../components/Layout';
import api from '../lib/api';

interface SearchMethod {
  id: string;
  name: string;
  icon: any;
  description: string;
  rateLimit: string;
  enabled: boolean;
}

interface Niche {
  id: string;
  name: string;
  selected: boolean;
}

const PREDEFINED_NICHES: Niche[] = [
  { id: 'clinica_medica', name: 'Clínica Médica', selected: false },
  { id: 'clinica_odontologica', name: 'Clínica Odontológica', selected: false },
  { id: 'clinica_veterinaria', name: 'Clínica Veterinária', selected: false },
  { id: 'escritorio_advocacia', name: 'Escritório de Advocacia', selected: false },
  { id: 'escritorio_contabilidade', name: 'Escritório de Contabilidade', selected: false },
  { id: 'consultoria_empresarial', name: 'Consultoria Empresarial', selected: false },
  { id: 'escola_particular', name: 'Escola Particular', selected: false },
  { id: 'imobiliaria', name: 'Imobiliária', selected: false },
  { id: 'academia', name: 'Academia/Fitness', selected: false },
  { id: 'restaurante', name: 'Restaurante', selected: false },
];

const REGIONS = [
  { id: 'grande_vitoria_es', name: 'Grande Vitória-ES', cities: ['Vitória', 'Vila Velha', 'Serra', 'Cariacica', 'Viana', 'Guarapari', 'Fundão'] },
  { id: 'grande_sp', name: 'Grande São Paulo-SP', cities: ['São Paulo', 'Guarulhos', 'Osasco', 'Santo André'] },
  { id: 'grande_rj', name: 'Grande Rio de Janeiro-RJ', cities: ['Rio de Janeiro', 'Niterói', 'Duque de Caxias'] },
  { id: 'grande_bh', name: 'Grande Belo Horizonte-MG', cities: ['Belo Horizonte', 'Contagem', 'Betim'] },
];

export default function MassiveSearch() {
  const router = useRouter();
  const [niches, setNiches] = useState<Niche[]>(PREDEFINED_NICHES);
  const [customNiche, setCustomNiche] = useState('');
  const [selectedRegion, setSelectedRegion] = useState('grande_vitoria_es');
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
  ]);

  const toggleNiche = (id: string) => {
    setNiches(niches.map(n => n.id === id ? { ...n, selected: !n.selected } : n));
  };

  const addCustomNiche = () => {
    if (customNiche.trim()) {
      const newNiche: Niche = {
        id: `custom_${Date.now()}`,
        name: customNiche.trim(),
        selected: true,
      };
      setNiches([...niches, newNiche]);
      setCustomNiche('');
    }
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
      const response = await api.post('/api/search/massive', {
        niches: selectedNiches,
        region: selectedRegion,
        methods: enabledMethods,
        max_pages: maxPages,
      });

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
    <Layout>
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
              <div className="flex items-center gap-2 mb-4">
                <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center text-blue-600 dark:text-blue-400 font-bold">
                  1
                </div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">Selecione os Nichos</h2>
              </div>

              <div className="grid grid-cols-2 gap-3 mb-4">
                {niches.map((niche) => (
                  <button
                    key={niche.id}
                    onClick={() => toggleNiche(niche.id)}
                    className={`p-3 rounded-lg border-2 transition-all ${
                      niche.selected
                        ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300'
                        : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 text-gray-700 dark:text-gray-300'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      {niche.selected && <CheckCircle2 className="h-4 w-4 flex-shrink-0" />}
                      <span className="text-sm font-medium">{niche.name}</span>
                    </div>
                  </button>
                ))}
              </div>

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
              </div>
            </div>

            {/* Step 3: Select Methods */}
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center text-blue-600 dark:text-blue-400 font-bold">
                  3
                </div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">Métodos de Extração</h2>
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
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Páginas por Busca: {maxPages}
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
                  <p className="text-blue-100 text-sm mb-1">Jobs Estimados</p>
                  <p className="text-3xl font-bold">{estimatedJobs}</p>
                </div>

                <button
                  onClick={handleStartMassiveSearch}
                  disabled={loading || selectedNichesCount === 0 || enabledMethodsCount === 0}
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
    </Layout>
  );
}
