import { Routes, Route, Navigate } from 'react-router-dom'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import Ads from '@/pages/ads'
import Products from '@/pages/Products'
import MappingManagement from '@/pages/products/MappingManagement'
import Seo from '@/pages/Seo'
import Reports from '@/pages/Reports'
import KeywordStats from '@/pages/reports/KeywordStats'
import RegionSales from '@/pages/reports/RegionSales'
import SearchInsights from '@/pages/reports/SearchInsights'
import Settings from '@/pages/Settings'
import AppLayout from '@/components/AppLayout'
import AuthRoute from '@/components/AuthRoute'

const App = () => {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <AuthRoute>
            <AppLayout />
          </AuthRoute>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="ads" element={<Ads />} />
        <Route path="ads/bid-management" element={<Ads />} />
        <Route path="products" element={<Products />} />
        <Route path="products/mapping" element={<MappingManagement />} />
        <Route path="seo" element={<Seo />} />
        <Route path="reports" element={<Reports />} />
        <Route path="reports/keywords" element={<KeywordStats />} />
        <Route path="reports/regions" element={<RegionSales />} />
        <Route path="reports/search-insights" element={<SearchInsights />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
