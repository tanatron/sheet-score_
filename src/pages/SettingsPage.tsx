import { useState, useEffect } from "react";
import { getApiBaseUrl, setApiBaseUrl, checkHealth } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";

export default function SettingsPage() {
  const [url, setUrl] = useState(getApiBaseUrl());
  const [testing, setTesting] = useState(false);

  const handleSave = () => {
    setApiBaseUrl(url);
    toast.success("บันทึก URL แล้ว");
  };

  const handleTest = async () => {
    setTesting(true);
    setApiBaseUrl(url);
    try {
      const r = await checkHealth();
      if (r.status === "ok") toast.success("เชื่อมต่อสำเร็จ ✓");
      else toast.error("API ตอบกลับไม่ถูกต้อง");
    } catch {
      toast.error("ไม่สามารถเชื่อมต่อได้");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="page-container space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-heading font-bold tracking-tight">ตั้งค่า</h1>
        <p className="text-muted-foreground mt-1">กำหนดค่าการเชื่อมต่อ API</p>
      </div>

      <Card className="card-elevated">
        <CardContent className="p-6 space-y-4">
          <div>
            <Label>API Base URL</Label>
            <Input
              className="mt-1.5 font-mono text-sm"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="http://localhost:8000"
            />
            <p className="text-xs text-muted-foreground mt-1.5">
              URL ของ FastAPI backend เช่น http://localhost:8000
            </p>
          </div>
          <div className="flex gap-3">
            <Button onClick={handleSave}>บันทึก</Button>
            <Button variant="outline" onClick={handleTest} disabled={testing}>
              {testing ? <><Loader2 className="w-4 h-4 animate-spin mr-1" /> ทดสอบ...</> : "ทดสอบการเชื่อมต่อ"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
