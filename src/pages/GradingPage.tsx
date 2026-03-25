import { useState, useCallback, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { listAnswerKeys, gradeSingle, gradeBatchDownload, getResultImageUrl, type GradeResult } from "@/lib/api";

import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Upload, ImageIcon, Download, CheckCircle2, XCircle, Loader2, FileSpreadsheet, FileText, StopCircle } from "lucide-react";
import { toast } from "sonner";
import { exportCSV, exportExcel } from "@/lib/export";

export default function GradingPage() {
  const keys = useQuery({ queryKey: ["answer-keys"], queryFn: listAnswerKeys });
  const [selectedKey, setSelectedKey] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [results, setResults] = useState<GradeResult[]>([]);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  // Batch progress state
  const [isGrading, setIsGrading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentFile, setCurrentFile] = useState("");
  const cancelRef = useRef(false);

  const isBatch = files.length > 1;

  const handleFiles = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFiles(Array.from(e.target.files));
      setResults([]);
      setPreviewUrl(null);
      setProgress(0);
    }
  }, []);

  const handleGrade = async () => {
    if (!selectedKey) return toast.error("กรุณาเลือกเฉลย");
    if (files.length === 0) return toast.error("กรุณาเลือกไฟล์");

    setIsGrading(true);
    cancelRef.current = false;
    setResults([]);
    setProgress(0);

    const total = files.length;
    const collected: GradeResult[] = [];

    for (let i = 0; i < total; i++) {
      if (cancelRef.current) {
        toast.info(`หยุดตรวจที่ ${i}/${total} ใบ`);
        break;
      }

      const file = files[i];
      setCurrentFile(file.name);
      setProgress(Math.round((i / total) * 100));

      try {
        const r = await gradeSingle(file, selectedKey);
        collected.push({ ...r, filename: r.filename || file.name });
      } catch (e) {
        collected.push({
          result_id: "",
          score: 0,
          total: 0,
          percentage: 0,
          details: {},
          image_url: "",
          filename: file.name,
          error: String(e),
        });
      }

      setResults([...collected]);
    }

    setProgress(100);
    setCurrentFile("");
    setIsGrading(false);

    if (!cancelRef.current) {
      toast.success(`ตรวจเสร็จ ${collected.length} ใบ`);
    }


  };

  const handleCancel = () => {
    cancelRef.current = true;
  };

  const handleDownloadZip = async () => {
    if (!selectedKey) return;
    try {
      const blob = await gradeBatchDownload(files, selectedKey);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "grading_results.zip";
      a.click();
      URL.revokeObjectURL(url);
      toast.success("ดาวน์โหลด ZIP แล้ว");
    } catch (e) {
      toast.error(String(e));
    }
  };

  return (
    <div className="page-container space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-heading font-bold tracking-tight">ตรวจข้อสอบ</h1>
        <p className="text-muted-foreground mt-1">อัพโหลดภาพกระดาษคำตอบเพื่อตรวจคะแนน</p>
      </div>

      <Card className="card-elevated">
        <CardContent className="p-6 space-y-5">
          {/* Key selection */}
          <div>
            <Label>เลือกชุดเฉลย</Label>
            <Select value={selectedKey} onValueChange={setSelectedKey}>
              <SelectTrigger className="mt-1.5">
                <SelectValue placeholder="เลือกเฉลย..." />
              </SelectTrigger>
              <SelectContent>
                {keys.data?.map((k) => (
                  <SelectItem key={k.id} value={k.id}>
                    {k.name} ({k.form_type === "A" ? "ข้อกา" : k.form_type === "B" ? "ข้อฝน" : `Type ${k.form_type}`}, {k.question_count} ข้อ)
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* File upload */}
          <div>
            <Label>อัพโหลดภาพ</Label>
            <label className="mt-1.5 flex flex-col items-center justify-center border-2 border-dashed border-border rounded-lg p-8 cursor-pointer hover:border-primary/50 hover:bg-primary/5 transition-colors">
              <Upload className="w-8 h-8 text-muted-foreground mb-2" />
              <span className="text-sm text-muted-foreground">คลิกเพื่อเลือกไฟล์ หรือลากไฟล์มาวาง</span>
              <span className="text-xs text-muted-foreground mt-1">รองรับ JPG, PNG — เลือกหลายไฟล์ได้</span>
              <input type="file" accept="image/*" multiple className="hidden" onChange={handleFiles} />
            </label>
            {files.length > 0 && (
              <p className="text-sm text-muted-foreground mt-2">
                เลือกแล้ว {files.length} ไฟล์ {isBatch && "(ตรวจแบบกลุ่ม)"}
              </p>
            )}
          </div>

          {/* Progress bar */}
          {isGrading && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground truncate max-w-[60%]">
                  กำลังตรวจ: {currentFile}
                </span>
                <span className="font-heading font-semibold text-primary">
                  {results.length}/{files.length} ใบ ({progress}%)
                </span>
              </div>
              <Progress value={progress} className="h-2.5" />
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 flex-wrap">
            {!isGrading ? (
              <Button onClick={handleGrade} disabled={!selectedKey || files.length === 0}>
                ตรวจข้อสอบ {isBatch && `(${files.length} ใบ)`}
              </Button>
            ) : (
              <Button variant="destructive" onClick={handleCancel}>
                <StopCircle className="w-4 h-4 mr-1" /> หยุดตรวจ
              </Button>
            )}
            {isBatch && !isGrading && (
              <Button variant="outline" onClick={handleDownloadZip} disabled={!selectedKey}>
                <Download className="w-4 h-4 mr-1" /> ตรวจ & ดาวน์โหลด ZIP
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Results */}
      {results.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h2 className="section-title">
              ผลการตรวจ ({results.length} ใบ)
              {results.length > 1 && (() => {
                const valid = results.filter(r => !r.error);
                if (valid.length === 0) return null;
                const avg = valid.reduce((s, r) => s + r.percentage, 0) / valid.length;
                return (
                  <span className="ml-2 text-sm font-normal text-muted-foreground">
                    — เฉลี่ย {avg.toFixed(1)}%
                  </span>
                );
              })()}
            </h2>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => { exportCSV(results, files.map(f => f.name)); toast.success("ส่งออก CSV แล้ว"); }}>
                <FileText className="w-4 h-4 mr-1" /> CSV
              </Button>
              <Button size="sm" variant="outline" onClick={() => { exportExcel(results, files.map(f => f.name)); toast.success("ส่งออก Excel แล้ว"); }}>
                <FileSpreadsheet className="w-4 h-4 mr-1" /> Excel
              </Button>
            </div>
          </div>

          {/* Summary table */}
          <Card className="card-elevated overflow-hidden">
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
                    <th className="text-center px-4 py-2.5 font-medium text-secondary-foreground">ภาพ</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {results.map((r, i) => (
                    <tr key={i} className="hover:bg-muted/50">
                      <td className="px-4 py-2.5 text-muted-foreground">{i + 1}</td>
                      <td className="px-4 py-2.5">{r.filename || files[i]?.name || `#${i + 1}`}</td>
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
                          <Button size="sm" variant="ghost" onClick={() => setPreviewUrl(getResultImageUrl(r.image_url))}>
                            <ImageIcon className="w-4 h-4" />
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Detail for single */}
          {results.length === 1 && results[0].details && !results[0].error && (
            <Card className="card-elevated">
              <CardContent className="p-4">
                <h3 className="section-title mb-3">รายละเอียดรายข้อ</h3>
                <div className="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-8 lg:grid-cols-10 gap-1.5">
                  {Object.entries(results[0].details).map(([q, d]) => (
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

      {/* Image preview modal */}
      {previewUrl && (
        <div className="fixed inset-0 z-50 bg-foreground/60 flex items-center justify-center p-4" onClick={() => setPreviewUrl(null)}>
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
