import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listAnswerKeys, checkHealth, listHistory } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { FileKey2, Activity, ClipboardCheck, AlertCircle, History } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";

export default function DashboardPage() {
  const health = useQuery({ queryKey: ["health"], queryFn: checkHealth, retry: 1 });
  const keys = useQuery({ queryKey: ["answer-keys"], queryFn: listAnswerKeys, retry: 1 });
  const historyQuery = useQuery({ queryKey: ["history"], queryFn: listHistory, retry: 1 });
  const recentHistory = historyQuery.data ? historyQuery.data.slice(0, 5) : [];

  const isOnline = health.data?.status === "ok";

  return (
    <div className="page-container space-y-8 animate-fade-in">
      <div>
        <h1 className="text-2xl font-heading font-bold tracking-tight">แดชบอร์ด</h1>
        <p className="text-muted-foreground mt-1">ระบบตรวจข้อสอบ OMR — จัดการเฉลยและตรวจข้อสอบ</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="stat-card">
          <CardContent className="p-0 flex items-center gap-4">
            <div className="w-11 h-11 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
              <Activity className="w-5 h-5 text-primary" />
            </div>
            <div>
              <p className="text-sm text-muted-foreground">สถานะ API</p>
              <p className="font-semibold font-heading">
                {health.isLoading ? "กำลังตรวจ..." : isOnline ? (
                  <span className="text-success">ออนไลน์</span>
                ) : (
                  <span className="text-destructive">ออฟไลน์</span>
                )}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="stat-card">
          <CardContent className="p-0 flex items-center gap-4">
            <div className="w-11 h-11 rounded-lg bg-accent/10 flex items-center justify-center shrink-0">
              <FileKey2 className="w-5 h-5 text-accent" />
            </div>
            <div>
              <p className="text-sm text-muted-foreground">ชุดเฉลย</p>
              <p className="font-semibold font-heading text-xl">{keys.data?.length ?? "—"}</p>
            </div>
          </CardContent>
        </Card>

        <Card className="stat-card">
          <CardContent className="p-0 flex items-center gap-4">
            <div className="w-11 h-11 rounded-lg bg-success/10 flex items-center justify-center shrink-0">
              <ClipboardCheck className="w-5 h-5 text-success" />
            </div>
            <div>
              <p className="text-sm text-muted-foreground">พร้อมตรวจ</p>
              <p className="font-semibold font-heading text-xl">{keys.data && keys.data.length > 0 ? "✓" : "—"}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {!isOnline && !health.isLoading && (
        <Card className="border-destructive/30 bg-destructive/5">
          <CardContent className="p-4 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-destructive mt-0.5 shrink-0" />
            <div>
              <p className="font-medium text-destructive">ไม่สามารถเชื่อมต่อ API ได้</p>
              <p className="text-sm text-muted-foreground mt-1">
                กรุณาตรวจสอบว่า backend กำลังทำงานอยู่ และตั้งค่า URL ให้ถูกต้องในหน้า{" "}
                <Link to="/settings" className="text-primary underline">ตั้งค่า</Link>
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent history */}
      {recentHistory.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="section-title">ประวัติล่าสุด</h2>
            <Button asChild variant="ghost" size="sm">
              <Link to="/history">ดูทั้งหมด</Link>
            </Button>
          </div>
          <div className="grid gap-2">
            {recentHistory.map((s) => (
              <Card key={s.id} className="card-elevated">
                <CardContent className="p-3 flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                    <History className="w-4 h-4 text-primary" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sm truncate">{s.answerKeyName}</p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(s.timestamp).toLocaleString("th-TH")} · {s.fileCount} ใบ · เฉลี่ย {s.averagePercentage}%
                    </p>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Quick actions */}
      <div>
        <h2 className="section-title mb-4">เริ่มต้นใช้งาน</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Card className="card-elevated p-6">
            <FileKey2 className="w-8 h-8 text-primary mb-3" />
            <h3 className="font-heading font-semibold mb-1">สร้างเฉลย</h3>
            <p className="text-sm text-muted-foreground mb-4">เพิ่มชุดเฉลยสำหรับใช้ตรวจข้อสอบ OMR</p>
            <Button asChild>
              <Link to="/answer-keys">จัดการเฉลย</Link>
            </Button>
          </Card>
          <Card className="card-elevated p-6">
            <ClipboardCheck className="w-8 h-8 text-accent mb-3" />
            <h3 className="font-heading font-semibold mb-1">ตรวจข้อสอบ</h3>
            <p className="text-sm text-muted-foreground mb-4">อัพโหลดภาพข้อสอบเพื่อตรวจคะแนนอัตโนมัติ</p>
            <Button asChild variant="secondary">
              <Link to="/grading">เริ่มตรวจ</Link>
            </Button>
          </Card>
        </div>
      </div>
    </div>
  );
}
