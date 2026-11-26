<template>
  <section class="wm-panel" data-testid="watermark-receipt-panel">
    <div class="wm-head">
      <div>
        <h3>复读回执 · 交付确认</h3>
        <p class="wm-hint" data-testid="watermark-confirm-hint">
          本页依据脱敏批次的确切输出复读回执，确认「这一版」可否交付。
          回执与样本、处理版本、批次绑定：别的批次通过不能替这一版解锁；
          没有可读水印的输出，正式交付下载保持锁定。
        </p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/mask_rule" data-testid="goto-mask-reread">前往脱敏规则页提交批次/复读</RouterLink>
        <button class="btn primary" type="button" data-testid="watermark-reload" :disabled="loading" @click="loadState">
          {{ loading ? '刷新中…' : '刷新回执与交付资格' }}
        </button>
      </div>
    </div>

    <p v-if="errorMessage" class="error-text" data-testid="watermark-error">{{ errorMessage }}</p>

    <div class="wm-summary" data-testid="delivery-summary">
      <span class="summary-card">批次总数 <b>{{ batches.length }}</b></span>
      <span class="summary-card ok">可正式交付 <b>{{ deliverableCount }}</b></span>
      <span class="summary-card bad">水印不可读/未复读 <b>{{ batches.length - deliverableCount }}</b></span>
      <span class="summary-card">回执总数 <b>{{ receipts.length }}</b></span>
    </div>

    <h4 class="section-title">按处理版本确认交付资格</h4>
    <div class="table-scroll">
      <table class="data-table" data-testid="watermark-delivery-table">
        <thead>
          <tr>
            <th>批次编号</th>
            <th>样本</th>
            <th>处理版本</th>
            <th>复读回执</th>
            <th>本版交付确认</th>
            <th>正式交付下载</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="batch in batches"
            :key="batch.id"
            :data-batch-id="batch.id"
            :data-sample-code="batch.sample_code"
            :data-version="batch.version"
            :data-eligible="String(batch.eligible)"
            :data-testid="`delivery-row-${batch.id}`"
          >
            <td>{{ batch.batch_no }} <span class="muted">#{{ batch.id }}</span></td>
            <td data-testid="`wm-sample-${batch.id}`">{{ batch.sample_code }}</td>
            <td data-testid="`wm-version-${batch.id}`">{{ batch.version }}</td>
            <td>
              <template v-if="batch.latest_receipt">
                <span :class="batch.latest_receipt.readable ? 'ok-text' : 'error-text'">
                  {{ batch.latest_receipt.receipt_no || `回执#${batch.latest_receipt.id ?? ''}` }}
                  ：{{ batch.latest_receipt.result }}
                </span>
                <span class="sub">{{ batch.latest_receipt.message }}</span>
              </template>
              <span v-else class="muted">尚未复读</span>
            </td>
            <td :data-testid="`delivery-confirm-${batch.id}`">
              <strong :class="batch.eligible ? 'ok-text' : 'error-text'">{{ batch.delivery_status }}</strong>
              <span class="sub">{{ batch.eligibility_message }}</span>
            </td>
            <td>
              <a
                v-if="batch.eligible"
                class="btn primary small"
                :href="deliveryHref(batch.id)"
                download
                :data-batch-id="batch.id"
                data-eligible="true"
                :data-testid="`download-batch-${batch.id}`"
              >
                <span :data-testid="`watermark-download-${batch.id}`">下载正式交付</span>
              </a>
              <button
                v-else
                class="btn small"
                type="button"
                disabled
                aria-disabled="true"
                data-eligible="false"
                :data-testid="`download-batch-${batch.id}`"
              >
                <span :data-testid="`watermark-download-${batch.id}`">不可下载</span>
              </button>
            </td>
          </tr>
          <tr v-if="!batches.length">
            <td colspan="6" class="empty-state" data-testid="watermark-delivery-empty">
              暂无脱敏批次与复读回执。请先到「脱敏规则」页的「输出水印复读」入口提交批次并发起复读。
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 class="section-title">复读回执历史引用</h4>
    <ul class="wm-history" data-testid="watermark-receipt-history">
      <li
        v-for="receipt in receipts"
        :key="String(receipt.id ?? `${receipt.batch_id}-${receipt.created_at}`)"
        :data-batch-id="receipt.batch_id ?? ''"
        :data-readable="String(receipt.readable)"
        :data-testid="`receipt-row-${receipt.id ?? receipt.batch_id}`"
      >
        <strong>{{ receipt.receipt_no || `复读回执#${receipt.id ?? ''}` }}</strong>
        <span :class="receipt.readable ? 'ok-text' : 'error-text'">{{ receipt.result }}</span>
        <span>
          适用于 {{ receipt.sample_code }} / {{ receipt.version }} /
          {{ receipt.batch_no }}（批次 #{{ receipt.batch_id ?? '?' }}）
        </span>
      </li>
      <li v-if="!receipts.length" class="muted">暂无回执历史。</li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { deliveryUrl, fetchRereadState, type MaskBatch, type RereadReceipt } from '@/api/reread'

const batches = ref<MaskBatch[]>([])
const receipts = ref<RereadReceipt[]>([])
const loading = ref(false)
const errorMessage = ref('')

const deliverableCount = computed(() => batches.value.filter((b) => b.eligible).length)

async function loadState(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const state = await fetchRereadState()
    batches.value = state.batches.sort((a, b) => a.id - b.id)
    receipts.value = state.receipts
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复读回执读取失败'
  } finally {
    loading.value = false
  }
}

function deliveryHref(batchId: number): string {
  return deliveryUrl(batchId)
}

onMounted(loadState)
</script>

<style scoped>
.wm-panel { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; margin: 12px 0 18px; }
.wm-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.wm-head h3 { margin: 0 0 6px; font-size: 16px; }
.wm-hint { color: var(--muted); font-size: 13px; line-height: 1.7; margin: 0; max-width: 820px; }
.wm-summary { display: flex; gap: 10px; flex-wrap: wrap; margin: 12px 0; }
.summary-card { border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; font-size: 13px; background: #f8fafc; }
.summary-card b { font-size: 16px; margin-left: 6px; }
.summary-card.ok b { color: #067647; }
.summary-card.bad b { color: #b42318; }
.section-title { margin: 16px 0 8px; font-size: 14px; }
.table-scroll { overflow-x: auto; }
.sub { display: block; color: var(--muted); font-size: 12px; margin-top: 2px; max-width: 320px; }
.muted { color: var(--muted); font-size: 13px; }
.ok-text { color: #067647; }
.error-text { color: #b42318; }
.btn.small { padding: 4px 10px; font-size: 12px; text-decoration: none; display: inline-block; }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
.wm-history { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.wm-history li { display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline; border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; background: #fafbfc; font-size: 13px; }
</style>
