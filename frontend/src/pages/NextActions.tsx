import GtdItemList from '../components/GtdItemList'

export default function NextActions() {
  return (
    <GtdItemList
      title="Next Actions"
      statusFilter="next_action"
      emptyTitle="No next actions"
      emptyDescription="Items triaged as Next Action will appear here."
    />
  )
}
