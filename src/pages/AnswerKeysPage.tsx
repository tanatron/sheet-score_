import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listAnswerKeys, createAnswerKey, deleteAnswerKey, type AnswerKeySummary } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter, DialogClose } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Trash2, Plus, FileKey2, MousePointerClick, Type, Braces } from "lucide-react";
import { toast } from "sonner";

export default function AnswerKeysPage() {
  const qc = useQueryClient();
  const keys = useQuery({ queryKey: ["answer-keys"], queryFn: listAnswerKeys });

  const deleteMut = useMutation({
    mutationFn: deleteAnswerKey,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["answer-keys"] }); toast.success("ลบเฉลยแล้ว"); },
  });

  return (
    <div className="page-container space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-heading font-bold tracking-tight">ชุดเฉลย</h1>
          <p className="text-muted-foreground mt-1">จัดการเฉลยสำหรับตรวจข้อสอบ</p>
        </div>
        <CreateAnswerKeyDialog />
      </div>

      {keys.isLoading && <p className="text-muted-foreground">กำลังโหลด...</p>}
      {keys.error && <p className="text-destructive">ไม่สามารถโหลดข้อมูลได้ — ตรวจสอบ API</p>}

      {keys.data && keys.data.length === 0 && (
        <Card className="card-elevated p-8 text-center">
          <FileKey2 className="w-12 h-12 text-muted-foreground mx-auto mb-3" />
          <p className="text-muted-foreground">ยังไม่มีชุดเฉลย — กดปุ่ม "สร้างเฉลย" เพื่อเริ่มต้น</p>
        </Card>
      )}

      <div className="grid gap-3">
        {keys.data?.map((k) => (
          <Card key={k.id} className="card-elevated">
            <CardContent className="p-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
                  <FileKey2 className="w-4 h-4 text-primary" />
                </div>
                <div>
                  <p className="font-medium">{k.name}</p>
                  <p className="text-xs text-muted-foreground">
                    Type {k.form_type} · {k.question_count} ข้อ · ID: {k.id}
                  </p>
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="text-muted-foreground hover:text-destructive"
                onClick={() => { if (confirm("ลบเฉลยนี้?")) deleteMut.mutate(k.id); }}
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

/* ── Helpers ── */

function parseTextAnswers(text: string): Record<string, string> {
  const cleaned = text.toUpperCase().replace(/[^A-E]/gi, "");
  const obj: Record<string, string> = {};
  for (let i = 0; i < cleaned.length; i++) {
    obj[String(i + 1)] = cleaned[i];
  }
  return obj;
}

function parseJsonAnswers(json: string): Record<string, string> | null {
  try {
    const parsed = JSON.parse(json);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
    const obj: Record<string, string> = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof v === "string") obj[k] = v.toUpperCase();
    }
    return Object.keys(obj).length > 0 ? obj : null;
  } catch {
    return null;
  }
}

/* ── Dialog ── */

function CreateAnswerKeyDialog() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [formType, setFormType] = useState("A");
  const [count, setCount] = useState(60);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [inputMode, setInputMode] = useState<"click" | "text" | "json">("click");
  const [textInput, setTextInput] = useState("");
  const [jsonInput, setJsonInput] = useState("");

  const mut = useMutation({
    mutationFn: () => {
      let finalAnswers = answers;
      if (inputMode === "text") {
        finalAnswers = parseTextAnswers(textInput);
      } else if (inputMode === "json") {
        const parsed = parseJsonAnswers(jsonInput);
        if (!parsed) { toast.error("JSON ไม่ถูกต้อง"); return Promise.reject("Invalid JSON"); }
        finalAnswers = parsed;
      }
      return createAnswerKey(name, formType, finalAnswers);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["answer-keys"] });
      toast.success("สร้างเฉลยแล้ว");
      setOpen(false);
      resetForm();
    },
    onError: (e) => toast.error(String(e)),
  });

  const choices = ["A", "B", "C", "D", "E"];

  const resetForm = () => {
    setName("");
    setAnswers({});
    setTextInput("");
    setJsonInput("");
  };

  const initAnswers = (n: number) => {
    const obj: Record<string, string> = {};
    for (let i = 1; i <= n; i++) obj[String(i)] = answers[String(i)] || "";
    setAnswers(obj);
    setCount(n);
  };

  const filledCount = () => {
    if (inputMode === "text") return parseTextAnswers(textInput);
    if (inputMode === "json") return parseJsonAnswers(jsonInput) || {};
    return answers;
  };

  const currentAnswerCount = Object.values(filledCount()).filter(Boolean).length;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button onClick={() => initAnswers(count)}>
          <Plus className="w-4 h-4 mr-1" /> สร้างเฉลย
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-heading">สร้างชุดเฉลยใหม่</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Row 1: name, form type, count */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <Label>ชื่อเฉลย</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="เช่น วิชาคณิตศาสตร์" />
            </div>
            <div>
              <Label>ประเภทฟอร์ม</Label>
              <Select value={formType} onValueChange={setFormType}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="A">Type A (YOLO)</SelectItem>
                  <SelectItem value="B">Type B (Blob)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {inputMode === "click" && (
              <div>
                <Label>จำนวนข้อ</Label>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  value={count}
                  onChange={(e) => initAnswers(Number(e.target.value) || 1)}
                />
              </div>
            )}
          </div>

          {/* Input mode tabs */}
          <Tabs value={inputMode} onValueChange={(v) => setInputMode(v as "click" | "text" | "json")}>
            <TabsList className="w-full">
              <TabsTrigger value="click" className="flex-1 gap-1.5">
                <MousePointerClick className="w-3.5 h-3.5" /> กดเลือก
              </TabsTrigger>
              <TabsTrigger value="text" className="flex-1 gap-1.5">
                <Type className="w-3.5 h-3.5" /> พิมพ์ตัวอักษร
              </TabsTrigger>
              <TabsTrigger value="json" className="flex-1 gap-1.5">
                <Braces className="w-3.5 h-3.5" /> JSON
              </TabsTrigger>
            </TabsList>

            {/* Mode: Click */}
            <TabsContent value="click" className="mt-3">
              <Label className="mb-2 block text-sm">เฉลย ({currentAnswerCount}/{count} ข้อ)</Label>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-10 gap-y-1.5 pr-10">
                {Array.from({ length: count }, (_, i) => i + 1).map((q) => (
                  <div key={q} className="flex items-center gap-3 py-0.5">
                    <span className="text-xs text-muted-foreground w-8 text-right font-mono shrink-0">{q}.</span>
                    <div className="flex gap-1.5">
                      {choices.map((c) => (
                        <button
                          key={c}
                          type="button"
                          className={`w-7 h-7 rounded text-xs font-medium transition-colors ${
                            answers[String(q)] === c
                              ? "bg-primary text-primary-foreground"
                              : "bg-secondary text-secondary-foreground hover:bg-secondary/70"
                          }`}
                          onClick={() => setAnswers((prev) => ({ ...prev, [String(q)]: c }))}
                        >
                          {c}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </TabsContent>

            {/* Mode: Text */}
            <TabsContent value="text" className="mt-3 space-y-2">
              <Label className="block text-sm">
                พิมพ์เฉลยต่อกัน เช่น <code className="bg-muted px-1.5 py-0.5 rounded text-xs">ABCDEBACDE</code>
              </Label>
              <p className="text-xs text-muted-foreground">ตัวอักษร A-E เท่านั้น · ตัวที่ 1 = ข้อ 1, ตัวที่ 2 = ข้อ 2, ...</p>
              <Textarea
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                placeholder="ABCDEABCDEABCDE..."
                className="font-mono text-sm min-h-[100px]"
              />
              {textInput && (
                <div className="text-xs text-muted-foreground">
                  อ่านได้ {Object.keys(parseTextAnswers(textInput)).length} ข้อ
                  {" · "}
                  <button
                    type="button"
                    className="text-primary underline"
                    onClick={() => {
                      const parsed = parseTextAnswers(textInput);
                      setAnswers(parsed);
                      setCount(Object.keys(parsed).length);
                      setInputMode("click");
                      toast.success("โหลดเฉลยเข้าโหมดกดเลือกแล้ว");
                    }}
                  >
                    ดูในโหมดกดเลือก
                  </button>
                </div>
              )}
            </TabsContent>

            {/* Mode: JSON */}
            <TabsContent value="json" className="mt-3 space-y-2">
              <Label className="block text-sm">วาง JSON เฉลย</Label>
              <p className="text-xs text-muted-foreground">
                รูปแบบ: <code className="bg-muted px-1.5 py-0.5 rounded">{'{"1":"A","2":"B","3":"C"}'}</code>
              </p>
              <Textarea
                value={jsonInput}
                onChange={(e) => setJsonInput(e.target.value)}
                placeholder='{"1":"A","2":"B","3":"C","4":"D","5":"E"}'
                className="font-mono text-sm min-h-[120px]"
              />
              {jsonInput && (() => {
                const parsed = parseJsonAnswers(jsonInput);
                return parsed ? (
                  <div className="text-xs text-muted-foreground">
                    ✅ อ่านได้ {Object.keys(parsed).length} ข้อ
                    {" · "}
                    <button
                      type="button"
                      className="text-primary underline"
                      onClick={() => {
                        setAnswers(parsed);
                        setCount(Object.keys(parsed).length);
                        setInputMode("click");
                        toast.success("โหลดเฉลยเข้าโหมดกดเลือกแล้ว");
                      }}
                    >
                      ดูในโหมดกดเลือก
                    </button>
                  </div>
                ) : (
                  <p className="text-xs text-destructive">❌ JSON ไม่ถูกต้อง</p>
                );
              })()}
            </TabsContent>
          </Tabs>
        </div>

        <DialogFooter className="mt-4">
          <DialogClose asChild><Button variant="outline">ยกเลิก</Button></DialogClose>
          <Button onClick={() => mut.mutate()} disabled={!name || mut.isPending}>
            {mut.isPending ? "กำลังบันทึก..." : "บันทึก"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
