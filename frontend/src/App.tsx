import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ConfigurePage from "./pages/ConfigurePage";
import GeneratePage from "./pages/GeneratePage";
import HistoryPage from "./pages/HistoryPage";
import PreviewPage from "./pages/PreviewPage";
import SettingsPage from "./pages/SettingsPage";
import UploadPage from "./pages/UploadPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<UploadPage />} />
        <Route path="/configure/:projectId" element={<ConfigurePage />} />
        <Route path="/generate/:projectId" element={<GeneratePage />} />
        <Route path="/preview/:projectId" element={<PreviewPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
