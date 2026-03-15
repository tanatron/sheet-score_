import { useState } from "react";
import { getGradingHistory, deleteGradingSession, clearGradingHistory, type GradingSession } from "@/lib/storage";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Trash2, History, Eye, CheckCircle2, XCircle, Eraser } from "lucide-react";
import { toast } from "sonner";

export default function HistoryPage() {
  const [history, setHistory] = useState(getGradingHistory);
  const [selected, setSelected] = useState<GradingSession | null>(null);

  const reload = () => setHistory(getGradingHistory());

  const handleDelete = (id: string) => {
    if (!confirm("ลบประวัตินี้?")) return;
    deleteGradingSession(id);
    reload();
    toast.success("ลบแล้ว");
  };

  const handleClearAll = () => {
    if (!confirm("ลบประวัติทั้งหมด?")) return;
    clearGradingHistory();
    reload();
    toast.success("ลบประวัติทั้งหมดแล้ว");
  };

  return (
    <div className="page-container space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-heading font-bold tracking-tight">ประวัติการตรวจ</h1>
          <p className="text-muted-foreground mt-1">ดูประวัติการตรวจข้อสอบที่ผ่านมา</p>
        </div>
        {history.length > 0 && (
          <Button variant="outline" size="sm" onClick={handleClearAll}>
            <Eraser className="w-4 h-4 mr-1" /> ล้างทั้งหมด
          </Button>
        )}
      </div>

      {history.length === 0 && (
        <Card className="card-elevated p-8 text-center">
          <History className="w-12 h-12 text-muted-foreground mx-auto mb-3" />
          <p className="text-muted-foreground">ยังไม่มีประวัติการตรวจ</p>
        </Card>
      )}

      <div className="grid gap-3">
        {history.map((s) => (
          <Card key={s.id} className="card-elevated">
            <CardContent className="p-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                  <History className="w-4 h-4 text-primary" />
                </div>
                <div className="min-w-0">
                  <p className="font-medium truncate">{s.answerKeyName}</p>
                  <p className="text-xs text-muted-foreground">
                    {new Date(s.timestamp).toLocaleString("th-TH")} · {s.fileCount} ใบ · เฉลี่ย {s.averagePercentage}%
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <Button variant="ghost" size="icon" onClick={() => setSelected(s)}>
                  <Eye className="w-4 h-4" />
                </Button>
                <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-destructive" onClick={() => handleDelete(s.id)}>
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Detail dialog */}
      <Dialog open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-heading">รายละเอียดการตรวจ</DialogTitle>
          </DialogHeader>
          {selected && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                <div><span className="text-muted-foreground">เฉลย:</span> <span className="font-medium">{selected.answerKeyName}</span></div>
                <div><span className="text-muted-foreground">จำนวน:</span> <span className="font-medium">{selected.fileCount} ใบ</span></div>
                <div><span className="text-muted-foreground">เฉลี่ย:</span> <span className="font-medium">{selected.averagePercentage}%</span></div>
                <div><span className="text-muted-foreground">เวลา:</span> <span className="font-medium">{new Date(selected.timestamp).toLocaleString("th-TH")}</span></div>
              </div>

              <Card className="overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-secondary">
                      <tr>
                        <th className="text-left px-4 py-2.5 font-medium text-secondary-foreground">#</th>
                        <th className="text-left px-4 py-2.5 font-medium text-secondary-foreground">ไฟล์</th>
                        <th className="text-left px-4 py-2.5 font-medium text-secondary-foreground">รหัสวิชา</th>
                        <th className="text-left px-4 py-2.5 font-medium text-secondary-foreground">รหัสนักเรียน</th>
                        <th className="text-center px-4 py-2.5 font-medium text-secondary-foreground">คะแนน</th>
                        <th className="text-center px-4 py-2.5 font-medium text-secondary-foreground">%</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {selected.results.map((r, i) => (
                        <tr key={i} className="hover:bg-muted/50">
                          <td className="px-4 py-2.5 text-muted-foreground">{i + 1}</td>
                          <td className="px-4 py-2.5">{r.filename || `#${i + 1}`}</td>
                          <td className="px-4 py-2.5 font-mono text-xs">{r.subject_code || "—"}</td>
                          <td className="px-4 py-2.5 font-mono text-xs">{r.student_id || "—"}</td>
                          <td className="px-4 py-2.5 text-center font-heading font-semibold">
                            {r.error ? <span className="text-destructive text-xs">{r.error}</span> : `${r.score}/${r.total}`}
                          </td>
                          <td className="px-4 py-2.5 text-center">
                            {r.percentage != null && !r.error && (
                              <span className={r.percentage >= 50 ? "badge-success" : "badge-error"}>
                                {r.percentage}%
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              {/* Show details for single result */}
              {selected.results.length === 1 && selected.results[0].details && !selected.results[0].error && (
                <Card>
                  <CardContent className="p-4">
                    <h3 className="section-title mb-3">รายละเอียดรายข้อ</h3>
                    <div className="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-8 lg:grid-cols-10 gap-1.5">
                      {Object.entries(selected.results[0].details).map(([q, d]) => (
                        <div
                          key={q}
                          className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${
                            d.is_correct
                              ? "bg-success/10 text-success"
                              : "bg-destructive/10 text-destructive"
                          }`}
                        >
                          {d.is_correct ? <CheckCircle2 className="w-3 h-3 shrink-0" /> : <XCircle className="w-3 h-3 shrink-0" />}
                          <span className="font-medium">{q}:</span>
                          <span>{d.given}</span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
