import { useEffect, useMemo, useState } from "react"
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  LoaderCircle,
  MapPin,
  ShieldAlert,
  Sparkles,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"

function severityLabel(level) {
  const mapping = {
    critical: { text: "特别紧急", className: "tea-badge tea-badge-critical" },
    high: { text: "高优先级", className: "tea-badge tea-badge-high" },
    medium: { text: "中等级别", className: "tea-badge tea-badge-medium" },
    low: { text: "低优先级", className: "tea-badge tea-badge-low" },
  }
  return mapping[level] || { text: "待判断", className: "tea-badge tea-badge-neutral" }
}

function scoreTone(score) {
  if (score == null) return "tea-score-neutral"
  if (score >= 85) return "tea-score-good"
  if (score >= 70) return "tea-score-mid"
  return "tea-score-risk"
}

function SubmittedNotice({ label }) {
  if (!label) return null

  return (
    <div className="tea-submitted-banner">
      <LoaderCircle className="h-4 w-4 tea-spin" />
      <span>{label}</span>
    </div>
  )
}

function SummaryBar() {
  const severity = severityLabel(props.severity)

  return (
    <div className="tea-summary-bar">
      <div className="tea-summary-item">
        <ShieldAlert className="h-4 w-4" />
        <span>阶段</span>
        <strong>{props.phase}</strong>
      </div>
      <div className="tea-summary-item">
        <MapPin className="h-4 w-4" />
        <span>位置</span>
        <strong>{props.locationText}</strong>
      </div>
      <div className="tea-summary-item">
        <AlertTriangle className="h-4 w-4" />
        <Badge className={severity.className}>{severity.text}</Badge>
      </div>
    </div>
  )
}

function PlanSelectionView() {
  const plans = props.plans || []
  const evaluation = props.evaluationSummary || {}
  const [selectedPlanId, setSelectedPlanId] = useState(props.selectedPlanId || "")
  const [submitted, setSubmitted] = useState(Boolean(props.submitted))

  useEffect(() => {
    setSelectedPlanId(props.selectedPlanId || "")
    setSubmitted(Boolean(props.submitted))
  }, [props.selectedPlanId, props.submitted])

  const selectedPlan = plans.find((plan) => plan.planId === selectedPlanId)

  return (
    <div className="tea-section-stack">
      <SubmittedNotice label={submitted ? "方案已提交，系统正在继续推进后续评估..." : ""} />

      <div className="tea-plan-grid">
        {plans.map((plan) => {
          const isSelected = selectedPlanId === plan.planId || plan.selected

          return (
            <Card
              key={plan.planId}
              className={`tea-plan-card ${isSelected ? "tea-plan-card-selected" : ""} ${submitted ? "tea-card-locked" : ""}`}
              onClick={() => {
                if (!submitted) setSelectedPlanId(plan.planId)
              }}
            >
              <CardHeader className="pb-3">
                <div className="tea-plan-topline">
                  <div className="tea-chip-row">
                    <Badge className="tea-chip">{plan.label}</Badge>
                    {isSelected ? <Badge className="tea-chip tea-chip-active">已选中</Badge> : null}
                  </div>
                  {evaluation.score != null ? (
                    <div className={`tea-score-pill ${scoreTone(evaluation.score)}`}>
                      评估预览 {evaluation.score}
                    </div>
                  ) : null}
                </div>
                <CardTitle className="tea-plan-title">{plan.title}</CardTitle>
                <CardDescription className="tea-plan-summary">{plan.summary}</CardDescription>
              </CardHeader>
              <CardContent className="tea-plan-content">
                {plan.advantages?.length ? (
                  <div className="tea-list-block">
                    <div className="tea-list-title tea-list-title-good">优势</div>
                    <ul className="tea-list">
                      {plan.advantages.map((item, index) => (
                        <li key={`adv-${index}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {plan.disadvantages?.length ? (
                  <div className="tea-list-block">
                    <div className="tea-list-title tea-list-title-warn">代价</div>
                    <ul className="tea-list">
                      {plan.disadvantages.map((item, index) => (
                        <li key={`dis-${index}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </CardContent>
              <CardFooter className="tea-plan-footer">
                <Button
                  className={`tea-secondary-btn ${isSelected ? "tea-secondary-btn-active" : ""}`}
                  variant="outline"
                  disabled={submitted}
                  onClick={(event) => {
                    event.stopPropagation()
                    setSelectedPlanId(plan.planId)
                  }}
                >
                  {isSelected ? "当前选择" : "先选中"}
                </Button>
              </CardFooter>
            </Card>
          )
        })}
      </div>

      <div className="tea-sticky-actionbar">
        <div className="tea-actionbar-copy">
          <div className="tea-actionbar-title">已选择</div>
          <div className="tea-actionbar-text">
            {selectedPlan ? selectedPlan.title : "请先选择一套方案"}
          </div>
        </div>
        <Button
          className="tea-primary-btn"
          disabled={submitted || !selectedPlan}
          onClick={async () => {
            if (!selectedPlan) return
            setSubmitted(true)
            await updateElement({ ...props, submitted: true, selectedPlanId: selectedPlan.planId })
            sendUserMessage(selectedPlan.userReply || selectedPlan.title || selectedPlan.planId)
          }}
        >
          {submitted ? "已提交" : "提交所选方案"}
          {!submitted ? <ChevronRight className="h-4 w-4 ml-1" /> : null}
        </Button>
      </div>
    </div>
  )
}

function ConfirmationView() {
  const evaluation = props.evaluationSummary || {}
  const selectedPlan = props.selectedPlan || {}
  const [submitted, setSubmitted] = useState(Boolean(props.submitted))
  const [decision, setDecision] = useState(props.decision || "")

  useEffect(() => {
    setSubmitted(Boolean(props.submitted))
    setDecision(props.decision || "")
  }, [props.submitted, props.decision])

  const bannerLabel =
    submitted && decision === "confirm"
      ? "已确认执行，系统正在生成最终方案..."
      : submitted && decision === "revise"
        ? "已请求返回调整，系统正在重新生成方案..."
        : ""

  return (
    <div className="tea-section-stack">
      <SubmittedNotice label={bannerLabel} />

      <Card className={`tea-confirm-card ${submitted ? "tea-card-locked" : ""}`}>
        <CardHeader>
          <div className="tea-confirm-headline">
            <Badge className="tea-chip tea-chip-accent">最终确认</Badge>
            {evaluation.score != null ? (
              <div className={`tea-score-pill ${scoreTone(evaluation.score)}`}>
                综合评分 {evaluation.score}
              </div>
            ) : null}
          </div>
          <CardTitle className="tea-plan-title">{selectedPlan.title || "当前方案"}</CardTitle>
          <CardDescription className="tea-plan-summary">
            {selectedPlan.summary || props.prompt}
          </CardDescription>
        </CardHeader>
        <CardContent className="tea-confirm-content">
          {evaluation.riskLevel ? (
            <div className="tea-inline-note">
              <AlertTriangle className="h-4 w-4" />
              风险等级：{evaluation.riskLevel}
            </div>
          ) : null}
          {evaluation.suggestions?.length ? (
            <div className="tea-list-block">
              <div className="tea-list-title tea-list-title-warn">重点提醒</div>
              <ul className="tea-list">
                {evaluation.suggestions.map((item, index) => (
                  <li key={`sug-${index}`}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardContent>
        <CardFooter className="tea-confirm-footer">
          <Button
            className="tea-primary-btn"
            disabled={submitted}
            onClick={async () => {
              setSubmitted(true)
              setDecision("confirm")
              await updateElement({ ...props, submitted: true, decision: "confirm" })
              sendUserMessage(props.confirmReply || "确认执行")
            }}
          >
            <CheckCircle2 className="h-4 w-4 mr-1" />
            {submitted && decision === "confirm" ? "已确认" : "确认执行"}
          </Button>
          <Button
            variant="outline"
            className={`tea-secondary-btn ${decision === "revise" ? "tea-secondary-btn-active" : ""}`}
            disabled={submitted}
            onClick={async () => {
              setSubmitted(true)
              setDecision("revise")
              await updateElement({ ...props, submitted: true, decision: "revise" })
              sendUserMessage(props.reviseReply || "返回调整")
            }}
          >
            {submitted && decision === "revise" ? "已提交调整" : "返回调整"}
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}

function InfoRequestView() {
  const [draft, setDraft] = useState(props.draft || "")
  const [submitted, setSubmitted] = useState(Boolean(props.submitted))

  useEffect(() => {
    setDraft(props.draft || "")
    setSubmitted(Boolean(props.submitted))
  }, [props.draft, props.submitted])

  const chips = useMemo(() => props.suggestedOptions || [], [props.suggestedOptions])

  return (
    <div className="tea-section-stack">
      <SubmittedNotice label={submitted ? "补充信息已提交，系统正在继续处理..." : ""} />

      <Card className={`tea-info-card ${submitted ? "tea-card-locked" : ""}`}>
        <CardHeader>
          <div className="tea-confirm-headline">
            <Badge className="tea-chip tea-chip-accent">补充信息</Badge>
            <Sparkles className="h-4 w-4 text-[var(--tea-accent)]" />
          </div>
          <CardTitle className="tea-plan-title">{props.title}</CardTitle>
          <CardDescription className="tea-plan-summary">
            {props.prompt}
          </CardDescription>
        </CardHeader>
        <CardContent className="tea-info-content">
          {props.reason ? (
            <div className="tea-inline-note">
              <ClipboardList className="h-4 w-4" />
              {props.reason}
            </div>
          ) : null}

          {chips.length ? (
            <div className="tea-chip-wrap">
              {chips.map((item, index) => (
                <button
                  key={`chip-${index}`}
                  className={`tea-option-chip ${draft === item ? "tea-option-chip-active" : ""}`}
                  onClick={() => {
                    if (!submitted) setDraft(item)
                  }}
                  disabled={submitted}
                  type="button"
                >
                  {item}
                </button>
              ))}
            </div>
          ) : null}

          <Textarea
            className="tea-textarea"
            placeholder={props.placeholder || "请输入补充信息"}
            value={draft}
            disabled={submitted}
            onChange={(event) => setDraft(event.target.value)}
          />
        </CardContent>
        <CardFooter className="tea-confirm-footer">
          <Button
            className="tea-primary-btn"
            disabled={submitted || !draft.trim()}
            onClick={async () => {
              const message = draft.trim()
              setSubmitted(true)
              await updateElement({ ...props, submitted: true, draft: message })
              sendUserMessage(message)
            }}
          >
            {submitted ? "已提交" : "提交信息"}
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}

function StallResumeView() {
  const [draft, setDraft] = useState(props.draft || "")
  const [submitted, setSubmitted] = useState(Boolean(props.submitted))
  const [action, setAction] = useState(props.action || "")

  useEffect(() => {
    setDraft(props.draft || "")
    setSubmitted(Boolean(props.submitted))
    setAction(props.action || "")
  }, [props.draft, props.submitted, props.action])

  const bannerLabel =
    submitted && action === "continue"
      ? "已请求模型继续行动，系统正在重新推进下一步..."
      : submitted && action === "refine"
        ? "补充 refine 已提交，系统正在按新条件继续处理..."
        : ""

  return (
    <div className="tea-section-stack">
      <SubmittedNotice label={bannerLabel} />

      <Card className={`tea-info-card tea-stall-card ${submitted ? "tea-card-locked" : ""}`}>
        <CardHeader>
          <div className="tea-confirm-headline">
            <Badge className="tea-chip tea-chip-accent">流程停住</Badge>
            <AlertTriangle className="h-4 w-4 text-[var(--tea-accent)]" />
          </div>
          <CardTitle className="tea-plan-title">{props.title}</CardTitle>
          <CardDescription className="tea-plan-summary">
            {props.subtitle || props.prompt}
          </CardDescription>
        </CardHeader>
        <CardContent className="tea-info-content">
          {props.reason ? (
            <div className="tea-inline-note">
              <ClipboardList className="h-4 w-4" />
              {props.reason}
            </div>
          ) : null}

          {props.stalledResponse ? (
            <div className="tea-stall-preview">
              <div className="tea-list-title">模型刚才的停住回复</div>
              <p>{props.stalledResponse}</p>
            </div>
          ) : null}

          <div className="tea-stall-grid">
            <div className="tea-stall-block">
              <div className="tea-list-title tea-list-title-good">继续行动</div>
              <p className="tea-plan-summary">
                直接告诉模型不要停在说明上，继续调用下一步所需工具，或者在条件齐备时直接完成最终方案。
              </p>
              <Button
                className="tea-primary-btn"
                disabled={submitted}
                onClick={async () => {
                  setSubmitted(true)
                  setAction("continue")
                  await updateElement({ ...props, submitted: true, action: "continue" })
                  sendUserMessage(props.continueReply || "请继续行动")
                }}
              >
                继续行动
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>

            <div className="tea-stall-block">
              <div className="tea-list-title tea-list-title-warn">补充 refine</div>
              <p className="tea-plan-summary">
                如果你想修正条件、补充现场信息、排除资源或强调偏好，可以直接输入后再继续推进。
              </p>
              <Textarea
                className="tea-textarea"
                placeholder={props.placeholder || "请输入新的修正信息"}
                value={draft}
                disabled={submitted}
                onChange={(event) => setDraft(event.target.value)}
              />
              <Button
                variant="outline"
                className="tea-secondary-btn"
                disabled={submitted || !draft.trim()}
                onClick={async () => {
                  const message = draft.trim()
                  setSubmitted(true)
                  setAction("refine")
                  await updateElement({ ...props, submitted: true, action: "refine", draft: message })
                  sendUserMessage(message)
                }}
              >
                提交 refine
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default function DecisionCards() {
  return (
    <div className="tea-decision-shell">
      <div className="tea-hero">
        <div className="tea-hero-copy">
          <div className="tea-kicker">Traffic Emergency Workflow</div>
          <h2 className="tea-title">{props.title || "指挥交互面板"}</h2>
          <p className="tea-subtitle">{props.subtitle || props.prompt}</p>
        </div>
        <SummaryBar />
      </div>

      {props.variant === "plan_selection" ? <PlanSelectionView /> : null}
      {props.variant === "confirmation" ? <ConfirmationView /> : null}
      {props.variant === "info_request" ? <InfoRequestView /> : null}
      {props.variant === "stall_resume" ? <StallResumeView /> : null}
    </div>
  )
}
