import React, { useEffect, useState } from 'react';
import { SecureAPI } from '../lib/secureApi';

interface RevenueData {
  property_id: string;
  timezone: string;
  reservations_count: number;
  totals: Array<{ currency: string; total_revenue: string; reservations_count: number }>;
}
interface RevenueSummaryProps { propertyId: string; month?: number; year?: number }

// Format the server's exact decimal string without converting money to float.
function formatMoney(amount: string): string {
  const [whole, fraction] = amount.split('.');
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fraction}`;
}

export const RevenueSummary: React.FC<RevenueSummaryProps> = ({ propertyId, month, year }) => {
  const [data, setData] = useState<RevenueData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setData(null);
    setError('');
    setLoading(true);
    SecureAPI.getDashboardSummary(propertyId, { month, year }).then(response => {
      if (active) setData(response);
    }).catch(() => { if (active) setError('Failed to load revenue data. Please try again.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [propertyId, month, year]);
  if (loading) return <div className="p-6" role="status">Loading revenue...</div>;
  if (error) return <div role="alert" className="p-4 text-red-600 bg-red-50 rounded-lg">{error}</div>;
  if (!data) return null;
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h2 className="text-sm font-medium text-gray-500 uppercase">Total Revenue</h2>
      {!data.totals.length && <p className="mt-3">No reservations in this period.</p>}
      {data.totals.map(item => <div key={item.currency} className="mt-3">
        <p className="text-3xl font-bold text-gray-900">{item.currency} {formatMoney(item.total_revenue)}</p>
        <p className="text-sm text-gray-500">{item.reservations_count} bookings</p>
      </div>)}
      <div className="grid grid-cols-2 gap-4 mt-6 pt-4 border-t border-gray-100">
        <div><p className="text-xs uppercase text-gray-500">Property ID</p><p>{data.property_id}</p></div>
        <div><p className="text-xs uppercase text-gray-500">Reservations</p><p>{data.reservations_count} bookings</p></div>
      </div>
      <p className="text-sm text-gray-500 mt-4">Timezone: {data.timezone}</p>
    </div>
  );
};
