import React, { useEffect, useState } from 'react';
import { RevenueSummary } from './RevenueSummary';
import { SecureAPI } from '../lib/secureApi';
import { useAuth } from '../contexts/AuthContext.new';

type Property = { id: string; name: string; timezone: string };

const Dashboard: React.FC = () => {
  const { user } = useAuth();
  const identity = `${user?.id}:${user?.tenant_id}`;
  // Remount account-specific state immediately when the authenticated user changes.
  return <TenantDashboard key={identity} identity={identity} />;
};

const TenantDashboard: React.FC<{ identity: string }> = ({ identity }) => {
  const [properties, setProperties] = useState<Property[]>([]);
  const [selectedProperty, setSelectedProperty] = useState('');
  const [period, setPeriod] = useState('monthly');
  const [month, setMonth] = useState(3);
  const [year, setYear] = useState(2024);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    SecureAPI.getDashboardProperties().then(items => {
      if (active) {
        setProperties(items);
        setSelectedProperty(items[0]?.id || '');
      }
    }).catch(() => { if (active) setError('Failed to load properties'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [identity]);
  return (
    <div className="p-4 lg:p-6 min-h-full">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold mb-6 text-gray-900">Property Management Dashboard</h1>
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 lg:p-6">
          <h2 className="text-xl font-medium mb-2">Revenue Overview</h2>
          <p className="text-gray-600 mb-6">Revenue by check-in date in the property's local time</p>
          {error && <p role="alert" className="text-red-600">{error}</p>}
          {loading && <p>Loading properties...</p>}
          {!loading && !error && !properties.length && <p>No properties available.</p>}
          {!!properties.length && <>
            <div className="flex flex-wrap gap-4 mb-6">
              <label>Select Property
                <select className="block border rounded p-2" value={selectedProperty} onChange={e => setSelectedProperty(e.target.value)}>
                  {properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </label>
              <label>Report period
                <select className="block border rounded p-2" value={period} onChange={e => setPeriod(e.target.value)}>
                  <option value="monthly">Monthly</option><option value="annual">Annual</option><option value="all">All time</option>
                </select>
              </label>
              {period === 'monthly' && <label>Month
                <select className="block border rounded p-2" value={month} onChange={e => setMonth(Number(e.target.value))}>
                  {Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{i + 1}</option>)}
                </select>
              </label>}
              {period !== 'all' && <label>Year
                <input aria-label="Year" className="block border rounded p-2 w-28" type="number" min="1" max="9998" value={year}
                  onChange={e => setYear(Number(e.target.value))} />
              </label>}
            </div>
            <RevenueSummary key={`${selectedProperty}:${period}:${month}:${year}`} propertyId={selectedProperty}
              month={period === 'monthly' ? month : undefined} year={period === 'all' ? undefined : year} />
          </>}
        </div>
      </div>
    </div>
  );
};
export default Dashboard;
