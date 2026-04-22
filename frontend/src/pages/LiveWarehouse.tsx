import { WarehousePage } from './VirtualWarehouse'

export default function LiveWarehouse() {
  return (
    <WarehousePage
      roleFilter="live"
      pageTitle="实盘仓"
      pageDescription="对接 QMT 实盘账户，独立展示资产、持仓、委托和成交，不写入跟踪看板。"
    />
  )
}
