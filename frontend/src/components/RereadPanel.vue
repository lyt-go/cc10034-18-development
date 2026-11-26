<template>
  <section class="reread-panel" data-testid="reread-panel">
    <div class="reread-head">
      <div>
        <h3>输出水印复读 · 交付前验证</h3>
        <p class="reread-invariant" data-testid="reread-binding-hint">
          完成脱敏处理后，把该批次的确切输出提交服务端做水印检测并生成复读回执。
          回执识别样本及处理版本并绑定确切批次：某一批复读通过，不能替另一批解锁；
          没有可读水印的输出不得下载为正式交付。样本被重处理、旧的复读凭据迟到时，
          下方会标明早先结果还能用于哪一次交付。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" data-testid="open-reread" @click="openForm">
          <span data-testid="reread-entry">新增复读入口 · 提交脱敏批次</span>
        </button>
        <button class="btn" type="button" data-testid="reload-reread" :disabled="loading" @click="loadState">
          {{ loading ? '刷新中…' : '刷新复读记录' }}
        </button>
      </div>
    </div>

    <div class="notice-stack" data-testid="cross-version-notices">
      <p
        v-for="notice in crossNotices"
        :key="notice.key"
        class="notice"
        :data-tone="notice.tone"
        :data-testid="`cross-notice-${notice.batchId}`"
      >
        {{ notice.text }}
      </p>
      <p
        v-for="flash in arrivalFlashes"
        :key="flash.key"
        class="notice flash"
        data-tone="info"
        :data-testid="`late-receipt-${flash.batchId}`"
      >
        {{ flash.text }}
      </p>
    </div>

    <p v-if="errorMessage" class="error-text" data-testid="reread-error">{{ errorMessage }}</p>

    <h4 class="section-title">脱敏批次、页面提示与交付资格</h4>
    <div class="table-scroll">
      <table class="data-table batch-table" data-testid="batch-table">
        <thead>
          <tr>
            <th>批次编号</th>
            <th>样本编号</th>
            <th>处理版本</th>
            <th>页面提示</th>
            <th>复读回执</th>
            <th>正式交付</th>
            <th>复读操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="batch in batches"
            :key="batch.id"
            :data-testid="`batch-row-${batch.id}`"
            :data-batch-id="batch.id"
            :data-sample-code="batch.sample_code"
            :data-version="batch.version"
            :data-eligible="String(batch.eligible)"
            :data-deliverable="String(batch.eligible)"
            :data-status="batch.status"
            :class="{ 'row-eligible': batch.eligible, 'row-blocked': !batch.eligible && !!batch.latest_receipt }"
          >
            <td>
              <strong :data-testid="`batch-no-${batch.id}`">{{ batch.batch_no }}</strong>
              <span class="sub">批次ID #{{ batch.id }}</span>
            </td>
            <td :data-testid="`batch-sample-cell-${batch.id}`">{{ batch.sample_code || '—' }}</td>
            <td :data-testid="`batch-version-cell-${batch.id}`">{{ batch.version || '—' }}</td>
            <td class="prompt-cell" :data-testid="`batch-prompt-${batch.id}`">
              <span class="prompt-text" :data-tone="promptTone(batch)">{{ promptFor(batch) }}</span>
              <span class="sub" :data-testid="`delivery-status-${batch.id}`">{{ batch.delivery_status }}</span>
            </td>
            <td :data-testid="`batch-receipt-cell-${batch.id}`">
              <template v-if="batch.latest_receipt">
                <span
                  class="receipt-badge"
                  :class="batch.latest_receipt.readable ? 'ok-text' : 'error-text'"
                  :data-testid="`receipt-result-${batch.id}`"
                >
                  {{ batch.latest_receipt.receipt_no || `复读回执#${batch.latest_receipt.id ?? '?'}` }}
                  ：{{ batch.latest_receipt.result }}
                </span>
                <span class="sub">{{ batch.latest_receipt.message }}</span>
                <span class="sub" :data-testid="`receipt-reference-${batch.id}`">
                  引用：样本 {{ batch.latest_receipt.sample_code || batch.sample_code }}
                  / 版本 {{ batch.latest_receipt.version || batch.version }}
                  / 批次 #{{ batch.latest_receipt.batch_id ?? batch.id }}
                </span>
              </template>
              <span v-else class="muted">尚未取得复读回执</span>
            </td>
            <td :data-testid="`delivery-cell-${batch.id}`">
              <a
                v-if="batch.eligible"
                class="btn primary small delivery-link"
                :href="deliveryHref(batch.id)"
                download
                :data-batch-id="batch.id"
                data-eligible="true"
                :data-testid="`download-batch-${batch.id}`"
              >
                <span :data-testid="`delivery-download-${batch.id}`">下载正式交付</span>
              </a>
              <button
                v-else
                class="btn small delivery-locked"
                type="button"
                disabled
                aria-disabled="true"
                data-eligible="false"
                :data-batch-id="batch.id"
                :data-testid="`download-batch-${batch.id}`"
              >
                <span :data-testid="`delivery-download-${batch.id}`">
                  {{ batch.latest_receipt ? '水印不可读 · 禁止下载' : '待复读 · 下载未解锁' }}
                </span>
              </button>
            </td>
            <td class="row-actions">
              <button
                class="link reread-action"
                type="button"
                :disabled="!!pending[batch.id]"
                :data-loading="String(!!pending[batch.id])"
                :data-testid="`reread-${batch.id}`"
                @click="onReread(batch)"
              >
                <span :data-testid="`action-${batch.id}-复读`">
                  {{ pending[batch.id] ? '复读检测中…' : batch.receipts.length ? '再次复读' : '发起复读' }}
                </span>
              </button>
            </td>
          </tr>
          <tr v-if="!batches.length">
            <td colspan="7" class="empty-state" data-testid="batch-empty">
              还没有脱敏批次。点击右上角「新增复读入口 · 提交脱敏批次」，可提交同一样本的两个处理版本进行核对。
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 class="section-title" id="receipt-history-title">复读回执历史与历史引用</h4>
    <ul class="receipt-history" data-testid="receipt-history">
      <li
        v-for="receipt in receipts"
        :key="receiptKey(receipt)"
        :data-receipt-id="receipt.id ?? ''"
        :data-batch-id="receipt.batch_id ?? ''"
        :data-readable="String(receipt.readable)"
        :data-testid="`receipt-row-${receipt.id ?? receipt.batch_id}`"
      >
        <div class="receipt-line">
          <strong>{{ receipt.receipt_no || `复读回执#${receipt.id ?? '临时'}` }}</strong>
          <span :class="receipt.readable ? 'ok-text' : 'error-text'" data-testid="history-result">
            {{ receipt.result }}
          </span>
          <span class="history-ref" data-testid="history-reference">
            历史引用 → 样本 <b>{{ receipt.sample_code || '—' }}</b>
            ／处理版本 <b>{{ receipt.version || '—' }}</b>
            ／批次编号 <b>{{ receipt.batch_no || '—' }}</b>
            ／批次ID <b>#{{ receipt.batch_id ?? '?' }}</b>
          </span>
        </div>
        <span class="sub">{{ receipt.message }} {{ receipt.created_at ? `（${receipt.created_at}）` : '' }}</span>
      </li>
      <li v-if="!receipts.length" class="muted" data-testid="receipt-empty">暂无复读回执，发起复读后在此保留历史引用。</li>
    </ul>

    <div v-if="showForm" class="modal-backdrop" data-testid="batch-modal">
      <form class="modal batch-form" data-testid="batch-form" @submit.prevent="submitBatch(false)">
        <h3 data-testid="reread-modal">新增复读 · 提交脱敏批次</h3>
        <p class="form-hint">
          提交后服务端保存这份「确切输出」，复读时只对它做水印检测。
          同一样本的两个处理版本请填写相同样本编号、不同处理版本。
        </p>
        <label class="create-field">
          <span>样本编号（相同样本保持一致）</span>
          <input
            v-model="form.sample_code"
            data-testid="batch-sample"
            placeholder="例如 SAMPLE-WM-001"
          />
        </label>
        <label class="create-field">
          <span>处理版本</span>
          <input
            v-model="form.version"
            data-testid="batch-version"
            placeholder="例如 v1 / v2"
          />
        </label>
        <label class="create-field">
          <span>关联水印编号（可选）</span>
          <input
            v-model="form.watermark_no"
            data-testid="batch-watermark"
            placeholder="例如 WATE-0001"
          />
        </label>
        <label class="create-field">
          <span>确切输出样本（JSON / CSV / 文本；水印必需字段：水印编号、水印标记）</span>
          <textarea
            v-model="form.outputText"
            rows="12"
            class="output-editor"
            data-testid="batch-output"
          ></textarea>
        </label>
        <div class="form-tools">
          <button class="btn ghost" type="button" data-testid="fill-valid-output" @click="fillValidOutput">
            填入带水印示例
          </button>
          <button
            class="btn ghost danger-ghost"
            type="button"
            data-testid="strip-watermark-fields"
            @click="stripWatermarkFields"
          >
            去掉水印所需字段
          </button>
        </div>
        <p v-if="formError" class="error-text" data-testid="batch-form-error">{{ formError }}</p>
        <div class="page-actions form-actions">
          <button class="btn" type="button" data-testid="cancel-batch" @click="showForm = false">
            取消
          </button>
          <button class="btn" type="button" :disabled="submitting" data-testid="submit-and-reread" @click="submitBatch(true)">
            {{ submitting ? '提交中…' : '提交并直接复读' }}
          </button>
          <button class="btn primary" type="submit" :disabled="submitting" data-testid="submit-batch">
            {{ submitting ? '提交中…' : '提交脱敏批次' }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  deliveryUrl,
  fetchRereadState,
  rereadBatch,
  submitMaskBatch,
  type MaskBatch,
  type RereadReceipt,
} from '@/api/reread'

const batches = ref<MaskBatch[]>([])
const receipts = ref<RereadReceipt[]>([])
const loading = ref(false)
const errorMessage = ref('')
const showForm = ref(false)
const submitting = ref(false)
const formError = ref('')
const pending = reactive<Record<number, boolean>>({})
const arrivalFlashes = ref<{ key: string; batchId: number; text: string }[]>([])

const VALID_OUTPUT_TEMPLATE = JSON.stringify(
  {
    样本编号: 'SAMPLE-WM-001',
    处理版本: 'v1',
    水印编号: 'WATE-0001',
    水印算法: 'LSB最低位替换',
    水印标记: 'WM-WATE-0001-7F3A9C21',
    records: [
      { 姓名: '张*', 手机号: '138****1234', 水印列: 'WM-WATE-0001-7F3A9C21' },
      { 姓名: '李*', 手机号: '139****5678', 水印列: 'WM-WATE-0001-7F3A9C21' },
    ],
  },
  null,
  2,
)

const form = reactive({
  sample_code: '',
  version: 'v1',
  watermark_no: 'WATE-0001',
  outputText: VALID_OUTPUT_TEMPLATE,
})

const MARKER_KEYS = [
  '水印标记', '水印签名', '水印内容', '水印码', '水印串', '水印值', '水印列',
  'watermark', 'watermark_token', 'watermark_marker', 'watermarkvalue',
  'wmtoken', 'wmmark', 'marker',
]
const IDENTITY_KEYS = ['水印编号', '水印id', '水印标识', 'watermarkid', 'watermarkno', 'watermarkcode']

function normKey(key: string): string {
  return key.trim().toLowerCase().replace(/[-_\s]/g, '')
}

function isWatermarkKey(key: string): boolean {
  const normalized = normKey(key)
  return [...MARKER_KEYS, ...IDENTITY_KEYS].some((candidate) => normalized === normKey(candidate))
}

function stripWatermarkDeep(node: unknown): unknown {
  if (Array.isArray(node)) return node.map(stripWatermarkDeep)
  if (node && typeof node === 'object') {
    return Object.fromEntries(
      Object.entries(node as Record<string, unknown>)
        .filter(([key]) => !isWatermarkKey(key))
        .map(([key, value]) => [key, stripWatermarkDeep(value)]),
    )
  }
  return node
}

async function loadState(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const state = await fetchRereadState()
    batches.value = state.batches.sort((a, b) => a.id - b.id)
    receipts.value = state.receipts
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复读记录读取失败'
  } finally {
    loading.value = false
  }
}

function openForm(): void {
  formError.value = ''
  showForm.value = true
}

function fillValidOutput(): void {
  form.outputText = VALID_OUTPUT_TEMPLATE
  formError.value = ''
}

function stripWatermarkFields(): void {
  try {
    const parsed = JSON.parse(form.outputText) as unknown
    form.outputText = JSON.stringify(stripWatermarkDeep(parsed), null, 2)
    formError.value = ''
  } catch {
    formError.value = '当前输出不是合法 JSON，无法按字段移除；可手动删除「水印编号」「水印标记」后提交。'
  }
}

function parseOutput(): unknown {
  const text = form.outputText.trim()
  if (!text) return {}
  try {
    return JSON.parse(text) as unknown
  } catch {
    return text // 非 JSON 时按原始文本提交，服务端仍会做文本水印检测。
  }
}

function upsertBatch(batch: MaskBatch): void {
  const index = batches.value.findIndex((item) => item.id === batch.id)
  if (index >= 0) batches.value[index] = batch
  else batches.value.push(batch)
  batches.value = [...batches.value].sort((a, b) => a.id - b.id)
}

function upsertReceipt(receipt: RereadReceipt): void {
  const key = receipt.id ?? `tmp-${receipt.batch_id}-${receipt.created_at}`
  const index = receipts.value.findIndex(
    (item) => (item.id ?? `tmp-${item.batch_id}-${item.created_at}`) === key,
  )
  if (index >= 0) receipts.value[index] = receipt
  else receipts.value.unshift(receipt)
}

async function submitBatch(autoReread: boolean): Promise<void> {
  submitting.value = true
  formError.value = ''
  try {
    const { batch, receipt } = await submitMaskBatch({
      sample_code: form.sample_code.trim(),
      version: form.version.trim(),
      watermark_no: form.watermark_no.trim(),
      output: parseOutput(),
      auto_reread: autoReread,
    })
    upsertBatch(batch)
    if (receipt) upsertReceipt(receipt)
    showForm.value = false
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '脱敏批次提交失败'
  } finally {
    submitting.value = false
  }
}

/**
 * 每个批次独立发起复读；调用闭包捕获 batch.id，响应按 receipt.batch_id
 * （不可信时回退请求 id）贴回对应行，因此交错返回不会串行/错贴。
 */
async function onReread(batch: MaskBatch): Promise<void> {
  const requestedId = batch.id
  pending[requestedId] = true
  errorMessage.value = ''
  try {
    const { receipt, batch: serverBatch } = await rereadBatch(requestedId)
    const targetId = receipt.batch_id ?? requestedId
    if (serverBatch && serverBatch.id === targetId) {
      upsertBatch(serverBatch)
    } else {
      const target = batches.value.find((item) => item.id === targetId)
      if (target) {
        target.latest_receipt = receipt
        target.receipts = [...target.receipts, receipt]
        target.receipt_count = target.receipts.length
        // 资格只增不降级：早先通过凭据始终是该批次的有效交付凭据。
        target.eligible = target.eligible || receipt.readable
        target.delivery_status = target.eligible
          ? '可正式交付'
          : receipt.readable
            ? '可正式交付'
            : '复读未通过·禁止正式交付'
        target.status = receipt.readable ? '复读通过' : '复读未通过'
        upsertBatch(target)
      }
    }
    upsertReceipt(receipt)
    maybeFlashLateReceipt(targetId, receipt)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复读请求失败'
  } finally {
    pending[requestedId] = false
  }
}

/** 迟到的旧批次凭据返回时，明确提示它仍适用于哪一次交付。 */
function maybeFlashLateReceipt(targetId: number, receipt: RereadReceipt): void {
  const sameSample = batches.value.filter((b) => b.sample_code && b.sample_code === receipt.sample_code)
  const latest = sameSample.sort((a, b) => b.id - a.id)[0]
  if (latest && latest.id > targetId) {
    const key = `late-${receipt.id ?? targetId}-${Date.now()}`
    arrivalFlashes.value.push({
      key,
      batchId: targetId,
      text:
        `迟到/交错返回的复读凭据已按批次身份贴回：${receipt.receipt_no || `回执#${receipt.id ?? ''}`} `
        + `仅适用于早先批次 #${targetId}（样本 ${receipt.sample_code} / 处理版本 ${receipt.version}）这一次交付，`
        + `不能用于当前最新批次 ${latest.batch_no}（${latest.version}）。`,
    })
    window.setTimeout(() => {
      arrivalFlashes.value = arrivalFlashes.value.filter((item) => item.key !== key)
    }, 12000)
  }
}

type CrossNotice = { key: string; batchId: number; tone: 'ok' | 'warn' | 'info'; text: string }

/** 按样本聚合，说明早先结果可用于哪次交付、当前版本为何未被解锁。 */
const crossNotices = computed<CrossNotice[]>(() => {
  const notices: CrossNotice[] = []
  const groups = new Map<string, MaskBatch[]>()
  for (const batch of batches.value) {
    if (!batch.sample_code) continue
    const list = groups.get(batch.sample_code) ?? []
    list.push(batch)
    groups.set(batch.sample_code, list)
  }
  for (const [sampleCode, list] of groups) {
    if (list.length < 2) continue
    const ordered = [...list].sort((a, b) => a.id - b.id)
    const latest = ordered[ordered.length - 1]
    for (const old of ordered.slice(0, -1)) {
      if (old.eligible) {
        notices.push({
          key: `early-${old.id}`,
          batchId: old.id,
          tone: 'ok',
          text:
            `样本 ${sampleCode} 已重处理到 ${latest.version}（批次 ${latest.batch_no}）。`
            + `迟到的复读凭据按批次归属：早先结果（${old.version} / ${old.batch_no}）`
            + `还能用于它所绑定的那一次交付，仅对该批次有效，`
            + `不能替新版本 ${latest.batch_no}（${latest.version}）解锁；某批通过不能替另一批解锁。`,
        })
      } else if (old.latest_receipt) {
        notices.push({
          key: `oldfail-${old.id}`,
          batchId: old.id,
          tone: 'warn',
          text: `早先批次 ${old.batch_no}（${old.version}）复读未通过，该次交付不可下载。`,
        })
      }
    }
    if (!latest.eligible && ordered.some((b) => b.eligible)) {
      const passBatch = ordered.find((b) => b.eligible)
      notices.push({
        key: `latest-locked-${latest.id}`,
        batchId: latest.id,
        tone: 'warn',
        text:
          `当前处理版本 ${latest.version}（批次 ${latest.batch_no}）尚未取得绑定本批次的通过回执，`
          + `即使同一样本的批次 ${passBatch?.batch_no ?? ''} 已通过，也不能替本批解锁交付资格。`,
      })
    }
  }
  return notices
})

function promptFor(batch: MaskBatch): string {
  if (batch.eligibility_message) return batch.eligibility_message
  if (batch.eligible) {
    return `复读通过：确切输出中的水印仍可辨认。回执仅绑定本批次 ${batch.batch_no}`
      + `（样本 ${batch.sample_code} / ${batch.version}），本版可以正式交付；该通过不能替其他批次解锁。`
  }
  if (batch.latest_receipt) {
    const missing = batch.latest_receipt.missing_fields?.length
      ? `（缺少水印必需字段：${batch.latest_receipt.missing_fields.join('、')}）`
      : ''
    return `复读未通过：没有可读水印${missing}，本版不具备交付资格，不得下载为正式交付。`
  }
  return '待复读：请对该批次的确切输出发起水印复读，通过前正式交付下载保持锁定。'
}

function promptTone(batch: MaskBatch): 'ok' | 'error' | 'muted' {
  if (batch.eligible) return 'ok'
  if (batch.latest_receipt) return 'error'
  return 'muted'
}

function deliveryHref(batchId: number): string {
  return deliveryUrl(batchId)
}

function receiptKey(receipt: RereadReceipt): string {
  return String(receipt.id ?? `tmp-${receipt.batch_id}-${receipt.created_at}`)
}

onMounted(loadState)
</script>

<style scoped>
.reread-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  margin: 12px 0 18px;
}
.reread-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.reread-head h3 { margin: 0 0 6px; font-size: 16px; }
.reread-invariant { color: var(--muted); font-size: 13px; margin: 0; max-width: 820px; line-height: 1.7; }
.section-title { margin: 16px 0 8px; font-size: 14px; }
.notice-stack { display: flex; flex-direction: column; gap: 6px; margin: 10px 0; }
.notice { margin: 0; padding: 8px 10px; border-radius: 6px; font-size: 12.5px; line-height: 1.6; background: #eff6ff; border: 1px solid #bfdbfe; color: #1e40af; }
.notice[data-tone='ok'] { background: #ecfdf3; border-color: #abefc6; color: #067647; }
.notice[data-tone='warn'] { background: #fffaeb; border-color: #fedf89; color: #b54708; }
.notice.flash { outline: 2px dashed #60a5fa; }
.table-scroll { overflow-x: auto; }
.batch-table { min-width: 960px; }
.prompt-cell { min-width: 260px; }
.prompt-text { display: block; font-size: 12.5px; line-height: 1.6; }
.prompt-text[data-tone='ok'] { color: #067647; }
.prompt-text[data-tone='error'] { color: #b42318; }
.prompt-text[data-tone='muted'] { color: var(--muted); }
.sub { display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }
.muted { color: var(--muted); font-size: 13px; }
.ok-text { color: #067647; font-weight: 600; }
.error-text { color: #b42318; font-weight: 600; }
.receipt-badge { display: inline-block; margin-bottom: 2px; }
.btn.small { padding: 4px 10px; font-size: 12px; }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
.delivery-link { text-decoration: none; display: inline-block; }
.receipt-history { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.receipt-history li { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; background: #fafbfc; display: flex; flex-direction: column; gap: 2px; }
.receipt-line { display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline; font-size: 13px; }
.history-ref { color: #334155; }
.output-editor { width: 100%; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; border: 1px solid var(--border); border-radius: 6px; padding: 8px; }
.form-tools { display: flex; gap: 8px; margin: 4px 0 8px; }
.danger-ghost { color: #b42318; }
.form-actions { justify-content: flex-end; margin-top: 8px; }
.form-hint { font-size: 12.5px; color: var(--muted); line-height: 1.6; }
.row-eligible { background: #f6fef9; }
.row-blocked { background: #fff7f6; }
</style>
