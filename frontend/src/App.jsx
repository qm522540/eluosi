import { Routes, Route, Navigate } from 'react-router-dom'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import Ads from '@/pages/ads'
import Products from '@/pages/Products'
import MappingManagement from '@/pages/products/MappingManagement'
import SeoOptimize from '@/pages/seo/Optimize'
import SeoHealth from '@/pages/seo/Health'
import SeoTracking from '@/pages/seo/Tracking'
import SeoReport from '@/pages/seo/Report'
import Reports from '@/pages/Reports'
import KeywordStats from '@/pages/reports/KeywordStats'
import SearchInsights from '@/pages/reports/SearchInsights'
import Settings from '@/pages/Settings'
import CloneTaskList from '@/pages/clone/CloneTaskList'
import PendingReview from '@/pages/clone/PendingReview'
import CloneLogs from '@/pages/clone/CloneLogs'
import Reviews from '@/pages/reviews/Reviews'
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
        <Route path="seo" element={<Navigate to="/seo/optimize" replace />} />
        <Route path="seo/optimize" element={<SeoOptimize />} />
        <Route path="seo/health" element={<SeoHealth />} />
        <Route path="seo/tracking" element={<SeoTracking />} />
        <Route path="seo/report" element={<SeoReport />} />
        <Route path="reports" element={<Reports />} />
        <Route path="reports/keywords" element={<KeywordStats />} />
        <Route path="reports/search-insights" element={<SearchInsights />} />
        <Route path="clone" element={<Navigate to="/clone/tasks" replace />} />
        <Route path="clone/tasks" element={<CloneTaskList />} />
        <Route path="clone/pending" element={<PendingReview />} />
        <Route path="clone/logs" element={<CloneLogs />} />
        <Route path="reviews" element={<Reviews />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
