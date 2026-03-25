import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { listHistory, getHistoryDetails, deleteHistorySession, getResultImageUrl, type HistorySessionSummary } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Trash2, History, Eye, CheckCircle2, XCircle, Eraser, Search, ArrowUpDown, ImageIcon } from "lucide-react";
import { toast } from "sonner";

export default function HistoryPage() {
  const [globalSearch, setGlobalSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(globalSearch), 400);
    return () => clearTimeout(timer);
  }, [globalSearch]);

  const { data: history = [], refetch, isFetching: isHistoryLoading } = useQuery({ 
    queryKey: ["history", debouncedSearch], 
    queryFn: () => listHistory(debouncedSearch) 
  });
  
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data: selectedSession, isLoading: isDetailsLoading } = useQuery({ 
    queryKey: ["history", selectedId], 
    queryFn: () => getHistoryDetails(selectedId!), 
    enabled: !!selectedId 
  });

  // 2. Dialog Sort & Filter Logic
  const handleSort = (key: string) => {
    let direction: 'asc' | 'desc' = 'asc';
    if (sortConfig && sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setSortConfig({ key, direction });
  };

  const getSortedResults = () => {
    if (!selectedSession) return [];
    let res = [...selectedSession.results];

    // Local filter
    if (dialogSearch) {
      const q = dialogSearch.toLowerCase();
      res = res.filter(r =>
        (r.student_id && r.student_id.toLowerCase().includes(q)) ||
        (r.subject_code && r.subject_code.toLowerCase().includes(q)) ||
        (r.filename && r.filename.toLowerCase().includes(q))
      );
    }

    // Sort
    if (sortConfig) {
      res.sort((a, b) => {
        let valA = a[sortConfig.key as keyof typeof a];
        let valB = b[sortConfig.key as keyof typeof b];

        // Ensure string comparisons are case-insensitive
        if (typeof valA === 'string') valA = valA.toLowerCase();
        if (typeof valB === 'string') valB = valB.toLowerCase();

        if (valA == null) valA = "";
        if (valB == null) valB = "";

        if (valA < valB) return sortConfig.direction === 'asc' ? -1 : 1;
        if (valA > valB) return sortConfig.direction === 'asc' ? 1 : -1;
        return 0;
      });
    }
    return res;
  };

  const [dialogSearch, setDialogSearch] = useState("");
  const [sortConfig, setSortConfig] = useState<{ key: string, direction: 'asc' | 'desc' } | null>(null);

  const handleDelete = async (id: string) => {
    if (!confirm("ลบประวัตินี้?")) return;
    try {
      await deleteHistorySession(id);
      refetch();
      toast.success("ลบแล้ว");
      if (selectedId === id) setSelectedId(null);
    } catch(e: any) {
      toast.error("ลบไม่ได้: " + e.message);
    }
  };

  return (
    <div className="page-container space-y-6 animate-fade-in">
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        <div>
          <h1 className="text-2xl font-heading font-bold tracking-tight">ประวัติการตรวจ</h1>
          <p className="text-muted-foreground mt-1">ดูประวัติการตรวจข้อสอบที่ผ่านมา</p>
        </div>
        <div className="flex gap-2 w-full sm:w-auto">
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input 
              placeholder="ค้นหาชื่อชุด, รหัสนักเรียน, หรือ รหัสวิชา..." 
              className="pl-8" 
              value={globalSearch}
              onChange={(e) => setGlobalSearch(e.target.value)}
            />
          </div>
        </div>
      </div>

      {history.length === 0 && (
        <Card className="card-elevated p-8 text-center">
          <History className="w-12 h-12 text-muted-foreground mx-auto mb-3" />
          <p className="text-muted-foreground">ยังไม่มีประวัติการตรวจ</p>
        </Card>
      )}

      {history.length > 0 && !isHistoryLoading && history.length === 0 && (
        <Card className="card-elevated p-8 text-center bg-muted/30">
          <Search className="w-10 h-10 text-muted-foreground mx-auto mb-3 opacity-50" />
          <p className="text-muted-foreground">ไม่พบประวัติที่ตรงกับ "{globalSearch}"</p>
        </Card>
      )}

      {isHistoryLoading && history.length === 0 && (
        <div className="py-12 text-center text-muted-foreground flex flex-col items-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mb-4"></div>
          กำลังโหลดประวัติ...
        </div>
      )}

      {!isHistoryLoading && history.length === 0 && !!globalSearch && (
        <Card className="card-elevated p-8 text-center bg-muted/30">
          <Search className="w-10 h-10 text-muted-foreground mx-auto mb-3 opacity-50" />
          <p className="text-muted-foreground">ไม่พบประวัติที่เกี่ยวกับ "{globalSearch}"</p>
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
                <Button variant="ghost" size="icon" onClick={() => setSelectedId(s.id)}>
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
      <Dialog open={!!selectedId} onOpenChange={(o) => {
        if (!o) {
          setSelectedId(null);
          setDialogSearch("");
          setSortConfig(null);
        }
      }}>
        <DialogContent className="max-w-4xl max-h-[85vh] overflow-y-auto w-[95vw] sm:w-full p-4 sm:p-6">
          <DialogHeader className="flex flex-col sm:flex-row items-start justify-between sm:items-center pr-8 sm:pr-0 gap-3 sm:gap-0">
            <DialogTitle className="font-heading mt-1">รายละเอียดการตรวจ</DialogTitle>
            {selectedSession && selectedSession.results.length > 1 && (
              <div className="relative w-full max-w-full sm:max-w-[200px] mt-0 mr-0 sm:mr-6">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input 
                  placeholder="ค้นหารหัสนักเรียน..." 
                  className="pl-8 h-9 text-sm" 
                  value={dialogSearch}
                  onChange={(e) => setDialogSearch(e.target.value)}
                />
              </div>
            )}
          </DialogHeader>
          
          {isDetailsLoading && (
            <div className="py-12 text-center text-muted-foreground flex flex-col items-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mb-4"></div>
              กำลังโหลดข้อมูล...
            </div>
          )}

          {!isDetailsLoading && selectedSession && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                <div><span className="text-muted-foreground">เฉลย:</span> <span className="font-medium">{selectedSession.answerKeyName}</span></div>
                <div><span className="text-muted-foreground">จำนวน:</span> <span className="font-medium">{selectedSession.fileCount} ใบ</span></div>
                <div><span className="text-muted-foreground">เฉลี่ย:</span> <span className="font-medium">{selectedSession.averagePercentage}%</span></div>
                <div><span className="text-muted-foreground">เวลา:</span> <span className="font-medium">{new Date(selectedSession.timestamp).toLocaleString("th-TH")}</span></div>
              </div>

              <Card className="overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-secondary">
                      <tr>
                        <th className="text-left px-4 py-2.5 font-medium text-secondary-foreground">#</th>
                        <th className="text-left px-4 py-2.5 font-medium text-secondary-foreground cursor-pointer hover:bg-secondary/80 select-none transition-colors" onClick={() => handleSort('filename')}>
                          ไฟล์ <ArrowUpDown className="inline w-3 h-3 ml-1 opacity-50"/>
                        </th>
                        <th className="text-left px-4 py-2.5 font-medium text-secondary-foreground cursor-pointer hover:bg-secondary/80 select-none transition-colors" onClick={() => handleSort('subject_code')}>
                          รหัสวิชา <ArrowUpDown className="inline w-3 h-3 ml-1 opacity-50"/>
                        </th>
                        <th className="text-left px-4 py-2.5 font-medium text-secondary-foreground cursor-pointer hover:bg-secondary/80 select-none transition-colors" onClick={() => handleSort('student_id')}>
                          รหัสนักเรียน <ArrowUpDown className="inline w-3 h-3 ml-1 opacity-50"/>
                        </th>
                        <th className="text-center px-4 py-2.5 font-medium text-secondary-foreground cursor-pointer hover:bg-secondary/80 select-none transition-colors" onClick={() => handleSort('score')}>
                          คะแนน <ArrowUpDown className="inline w-3 h-3 ml-1 opacity-50"/>
                        </th>
                        <th className="text-center px-4 py-2.5 font-medium text-secondary-foreground cursor-pointer hover:bg-secondary/80 select-none transition-colors" onClick={() => handleSort('percentage')}>
                          % <ArrowUpDown className="inline w-3 h-3 ml-1 opacity-50"/>
                        </th>
                        <th className="text-center px-4 py-2.5 font-medium text-secondary-foreground">ภาพ</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {getSortedResults().map((r, i) => (
                        <tr key={i} className="hover:bg-muted/50 transition-colors">
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
                          <td className="px-4 py-2.5 text-center">
                            {r.image_url && (
                              <Button size="sm" variant="ghost" onClick={() => setPreviewUrl(getResultImageUrl(r.image_url!))}>
                                <ImageIcon className="w-4 h-4" />
                              </Button>
                            )}
                          </td>
                        </tr>
                      ))}
                       {getSortedResults().length === 0 && (
                         <tr>
                           <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                             ไม่พบข้อมูลผลลัพธ์
                           </td>
                         </tr>
                       )}
                    </tbody>
                  </table>
                </div>
              </Card>

              {/* Show details for single result */}
              {selectedSession.results.length === 1 && selectedSession.results[0].details && !selectedSession.results[0].error && (
                <Card>
                  <CardContent className="p-4">
                    <h3 className="section-title mb-3">รายละเอียดรายข้อ</h3>
                    <div className="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-8 lg:grid-cols-10 gap-1.5">
                      {Object.entries(selectedSession.results[0].details).map(([q, d]) => (
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

      {/* Image preview modal */}
      {previewUrl && (
        <div className="fixed inset-0 z-[100] bg-foreground/60 flex items-center justify-center p-4" onClick={() => setPreviewUrl(null)}>
          <div className="max-w-4xl max-h-[90vh] overflow-auto bg-card rounded-xl shadow-xl p-2" onClick={(e) => e.stopPropagation()}>
            <img src={previewUrl} alt="Annotated result" className="w-full rounded-lg" />
            <div className="text-center mt-2">
              <Button size="sm" variant="outline" onClick={() => setPreviewUrl(null)}>ปิด</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
