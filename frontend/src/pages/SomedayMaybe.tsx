import GtdItemList from '../components/GtdItemList'

export default function SomedayMaybe() {
  return (
    <GtdItemList
      title="Someday / Maybe"
      statusFilter="someday_maybe"
      emptyTitle="No someday items"
      emptyDescription="Items triaged as Someday/Maybe will appear here."
    />
  )
}
