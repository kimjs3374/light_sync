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
import DeliveryProjectDetail from './pages/DeliveryProjectDetail';
import PurchaseOrderDetail from './pages/PurchaseOrderDetail';
import PurchaseOrderCreate from './pages/PurchaseOrderCreate';
import ReceivingDetail from './pages/ReceivingDetail';
import ProductionDetail from './pages/ProductionDetail';
import ProductionSites from './pages/ProductionSites';
import WarrantyDetail from './pages/WarrantyDetail';
import CreateForm from './pages/CreateForm';
import QuotationDetail from './pages/QuotationDetail';
import QuotationCreate from './pages/QuotationCreate';
import SalesDetail from './pages/SalesDetail';
import GenericList from './pages/GenericList';
import BusinessTrips from './pages/BusinessTrips';
import VehicleLogs from './pages/VehicleLogs';
import Photos from './pages/Photos';
import Drawings from './pages/Drawings';
import Tools from './pages/Tools';
import ReceivingPhotos from './pages/ReceivingPhotos';
import WarrantyCreate from './pages/WarrantyCreate';
import ProcessingOrderDetail from './pages/ProcessingOrderDetail';
import ProcessingOrderCreate from './pages/ProcessingOrderCreate';
import ReceivingCreate from './pages/ReceivingCreate';
import VendorDetail from './pages/VendorDetail';
import VendorCreate from './pages/VendorCreate';
import BillingDetail from './pages/BillingDetail';
import CertificationDetail from './pages/CertificationDetail';
import CertificationCreate from './pages/CertificationCreate';
import FinancialDashboard from './pages/FinancialDashboard';
import IlluminanceDetail from './pages/IlluminanceDetail';
import IlluminanceArea from './pages/IlluminanceArea';
import {
  Contracts, Sales, Deliveries,
  PurchaseOrders, Receivings, Materials, Quotations,
  Inventory, Items, Vendors, Warranty, Procurements,
  Documents, Billing, Certifications, ProcessingOrders,
  Illuminance,
} from './pages/lists';
import DocumentDetail from './pages/DocumentDetail';
import IncomingOverview from './pages/IncomingOverview';

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
        <Route path="/delivery-projects/:pid" element={<P><DeliveryProjectDetail /></P>} />
        <Route path="/deliveries/:id" element={<P><DeliveryDetail /></P>} />
        <Route path="/quotations" element={<P><Quotations /></P>} />
        <Route path="/quotations/create" element={<P><QuotationCreate /></P>} />
        <Route path="/quotations/:id" element={<P><QuotationDetail /></P>} />
        <Route path="/design" element={<P><GenericList /></P>} />
        <Route path="/documents" element={<P><Documents /></P>} />
        <Route path="/documents/:reqNo" element={<P><DocumentDetail /></P>} />
        <Route path="/illuminance" element={<P><Illuminance /></P>} />
        <Route path="/illuminance/:id" element={<P><IlluminanceDetail /></P>} />
        <Route path="/illuminance/:projectId/area/:areaId" element={<P><IlluminanceArea /></P>} />

        {/* 관리부 */}
        <Route path="/purchase-orders" element={<P><PurchaseOrders /></P>} />
        <Route path="/purchase-orders/create" element={<P><PurchaseOrderCreate /></P>} />
        <Route path="/purchase-orders/:id" element={<P><PurchaseOrderDetail /></P>} />
        <Route path="/receivings" element={<P><Receivings /></P>} />
        <Route path="/receivings/create" element={<P><ReceivingCreate /></P>} />
        <Route path="/receivings/:id" element={<P><ReceivingDetail /></P>} />
        <Route path="/vendors" element={<P><Vendors /></P>} />
        <Route path="/vendors/create" element={<P><VendorCreate /></P>} />
        <Route path="/vendors/:id" element={<P><VendorDetail /></P>} />
        <Route path="/processing-orders" element={<P><ProcessingOrders /></P>} />
        <Route path="/processing-orders/create" element={<P><ProcessingOrderCreate /></P>} />
        <Route path="/processing-orders/:id" element={<P><ProcessingOrderDetail /></P>} />
        <Route path="/financial" element={<P><FinancialDashboard /></P>} />
        <Route path="/billing" element={<P><Billing /></P>} />
        <Route path="/billing/:id" element={<P><BillingDetail /></P>} />
        <Route path="/certifications" element={<P><Certifications /></P>} />
        <Route path="/certifications/create" element={<P><CertificationCreate /></P>} />
        <Route path="/certifications/:id" element={<P><CertificationDetail /></P>} />

        {/* 자재/재고 */}
        <Route path="/materials" element={<P><Materials /></P>} />
        <Route path="/inventory" element={<P><Inventory /></P>} />
        <Route path="/items" element={<P><Items /></P>} />
        <Route path="/bom" element={<P><GenericList /></P>} />

        {/* 생산부 */}
        <Route path="/production" element={<P><ProductionSites /></P>} />
        <Route path="/production-site/:id" element={<P><ProductionDetail /></P>} />
        <Route path="/incoming" element={<P><IncomingOverview /></P>} />

        {/* 공통메뉴 */}
        <Route path="/procurements" element={<P><Procurements /></P>} />
        <Route path="/warranty" element={<P><Warranty /></P>} />
        <Route path="/warranty/create" element={<P><WarrantyCreate /></P>} />
        <Route path="/warranty/:id" element={<P><WarrantyDetail /></P>} />
        <Route path="/photos" element={<P><Photos /></P>} />
        <Route path="/drawings" element={<P><Drawings /></P>} />
        <Route path="/receiving-photos" element={<P><ReceivingPhotos /></P>} />
        <Route path="/business-trips" element={<P><BusinessTrips /></P>} />
        <Route path="/vehicle-logs" element={<P><VehicleLogs /></P>} />
        <Route path="/tools" element={<P><Tools /></P>} />

        <Route path="/create" element={<P><CreateForm /></P>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
