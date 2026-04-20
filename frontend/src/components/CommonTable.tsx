import React from 'react'

type CommonTableProps = {
  children: React.ReactNode
}

export function CommonTable({ children }: CommonTableProps) {
  return (
    <div className="common-table" role="table">
      {children}
    </div>
  )
}
