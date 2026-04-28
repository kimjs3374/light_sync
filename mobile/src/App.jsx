import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './hooks/useAuth';
import BottomNav from './components/BottomNav';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Projects from './pages/Projects';
import ProjectDetail from './pages/ProjectDetail';
import Notifications from './pages/Notifications';
import More from './pages/More';
import ContractDetail from './pages/ContractDetail';
import DeliveryDetail from './pages/DeliveryDetail';
import PurchaseOrderDetail from './pages/PurchaseOrderDetail';
import ReceivingDetail from './pages/ReceivingDetail';
import ProductionDetail from './pages/ProductionDetail';
import ProductionSites from './pages/ProductionSites';
import WarrantyDetail from './pages/WarrantyDetail';
import CreateForm from './pages/CreateForm';
import QuotationDetail from './pages/QuotationDetail';
import SalesDetail from './pages/SalesDetail';
import GenericList from './pages/GenericList';
import {
  Contracts, Sales, Deliveries,
  PurchaseOrders, Receivings, Materials, Quotations,
  Inventory, Items, Vendors, Warranty, Procurements,
} from './pages/lists';

function P({ children }) {
  const isLoggedIn = useAuth((s) => s.isLoggedIn);
  if (!isLoggedIn) return <Navigate to="/login" replace />;
  return <>{children}<BottomNav /></>;
}

export default function App() {
  return (
    <BrowserRouter basename="/m">
      <Routes>
        <Route path="/login" element={<Login />} />

        <Route path="/" element={<P><Dashboard /></P>} />
        <Route path="/projects" element={<P><Projects /></P>} />
        <Route path="/projects/:id" element={<P><ProjectDetail /></P>} />
        <Route path="/notifications" element={<P><Notifications /></P>} />
        <Route path="/more" element={<P><More /></P>} />

        {/* 영업부 */}
        <Route path="/contracts" element={<P><Contracts /></P>} />
        <Route path="/contracts/:id" element={<P><ContractDetail /></P>} />
        <Route path="/sales" element={<P><Sales /></P>} />
        <Route path="/sales/:id" element={<P><SalesDetail /></P>} />
        <Route path="/deliveries" element={<P><Deliveries /></P>} />
        <Route path="/deliveries/:id" element={<P><DeliveryDetail /></P>} />
        <Route path="/quotations" element={<P><Quotations /></P>} />
        <Route path="/quotations/:id" element={<P><QuotationDetail /></P>} />
        <Route path="/design" element={<P><GenericList /></P>} />
        <Route path="/documents" element={<P><GenericList /></P>} />

        {/* 관리부 */}
        <Route path="/purchase-orders" element={<P><PurchaseOrders /></P>} />
        <Route path="/purchase-orders/:id" element={<P><PurchaseOrderDetail /></P>} />
        <Route path="/receivings" element={<P><Receivings /></P>} />
        <Route path="/receivings/:id" element={<P><ReceivingDetail /></P>} />
        <Route path="/vendors" element={<P><Vendors /></P>} />
        <Route path="/processing-orders" element={<P><GenericList /></P>} />
        <Route path="/financial" element={<P><GenericList /></P>} />
        <Route path="/billing" element={<P><GenericList /></P>} />
        <Route path="/certifications" element={<P><GenericList /></P>} />

        {/* 자재/재고 */}
        <Route path="/materials" element={<P><Materials /></P>} />
        <Route path="/inventory" element={<P><Inventory /></P>} />
        <Route path="/items" element={<P><Items /></P>} />
        <Route path="/bom" element={<P><GenericList /></P>} />

        {/* 생산부 */}
        <Route path="/production" element={<P><ProductionSites /></P>} />
        <Route path="/production-site/:id" element={<P><ProductionDetail /></P>} />

        {/* 공통메뉴 */}
        <Route path="/procurements" element={<P><Procurements /></P>} />
        <Route path="/warranty" element={<P><Warranty /></P>} />
        <Route path="/warranty/:id" element={<P><WarrantyDetail /></P>} />
        <Route path="/photos" element={<P><GenericList /></P>} />
        <Route path="/drawings" element={<P><GenericList /></P>} />
        <Route path="/receiving-photos" element={<P><GenericList /></P>} />
        <Route path="/business-trips" element={<P><GenericList /></P>} />
        <Route path="/tools" element={<P><GenericList /></P>} />

        <Route path="/create" element={<P><CreateForm /></P>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
