/**
 * @name Statement has no effect except Protocol method bodies
 * @description A statement has no effect unless it is the intentional ellipsis body of a Protocol method
 * @kind problem
 * @tags quality
 *       maintainability
 *       useless-code
 *       external/cwe/cwe-561
 * @problem.severity recommendation
 * @sub-severity high
 * @precision high
 * @id py/ineffectual-statement-except-protocol
 */

import python
private import LegacyPointsTo

predicate understood_attribute(Attribute attr, ClassValue cls, ClassValue attr_cls) {
  exists(string name | attr.getName() = name |
    attr.getObject().(ExprWithPointsTo).pointsTo().getClass() = cls and
    cls.attr(name).getClass() = attr_cls
  )
}

predicate side_effecting_attribute(Attribute attr) {
  exists(ClassValue attr_cls |
    understood_attribute(attr, _, attr_cls) and
    side_effecting_descriptor_type(attr_cls)
  )
}

predicate maybe_side_effecting_attribute(Attribute attr) {
  not understood_attribute(attr, _, _) and not attr.(ExprWithPointsTo).pointsTo(_)
  or
  side_effecting_attribute(attr)
}

predicate side_effecting_descriptor_type(ClassValue descriptor) {
  descriptor.isDescriptorType() and
  not descriptor = ClassValue::functionType() and
  not descriptor = ClassValue::staticmethod() and
  not descriptor = ClassValue::classmethod()
}

predicate side_effecting_binary(Expr b) {
  exists(Expr sub, ClassValue cls, string method_name |
    binary_operator_special_method(b, sub, cls, method_name)
    or
    comparison_special_method(b, sub, cls, method_name)
  |
    method_name = special_method() and
    cls.hasAttribute(method_name) and
    not exists(ClassValue declaring |
      declaring.declaresAttribute(method_name) and
      declaring = cls.getASuperType() and
      declaring.isBuiltin() and
      not declaring = ClassValue::object()
    )
  )
}

pragma[nomagic]
private predicate binary_operator_special_method(
  BinaryExpr b, ExprWithPointsTo sub, ClassValue cls, string method_name
) {
  method_name = special_method() and
  sub = b.getLeft() and
  method_name = b.getOp().getSpecialMethodName() and
  sub.pointsTo().getClass() = cls
}

pragma[nomagic]
private predicate comparison_special_method(
  Compare b, ExprWithPointsTo sub, ClassValue cls, string method_name
) {
  exists(Cmpop op |
    b.compares(sub, op, _) and
    method_name = op.getSpecialMethodName()
  ) and
  sub.pointsTo().getClass() = cls
}

private string special_method() {
  result = any(Cmpop c).getSpecialMethodName()
  or
  result = any(BinaryExpr b).getOp().getSpecialMethodName()
}

predicate is_notebook(File f) {
  exists(Comment c | c.getLocation().getFile() = f |
    c.getText().regexpMatch("#\\s*<nbformat>.+</nbformat>\\s*")
  )
}

predicate in_notebook(Expr e) { is_notebook(e.getScope().(Module).getFile()) }

FunctionValue assertRaises() {
  result = Value::named("unittest.TestCase").(ClassValue).lookup("assertRaises")
}

predicate in_raises_test(Expr e) {
  exists(With w |
    w.contains(e) and
    w.getContextExpr() = assertRaises().getACall().getNode()
  )
}

predicate python2_print(Expr e) {
  e.(BinaryExpr).getLeft().(Name).getId() = "print" and
  e.(BinaryExpr).getOp() instanceof RShift
  or
  python2_print(e.(Tuple).getElt(0))
}

predicate no_effect(Expr e) {
  not e instanceof StringLiteral and
  not e.hasSideEffects() and
  forall(Expr sub | sub = e.getASubExpression*() |
    not side_effecting_binary(sub) and
    not maybe_side_effecting_attribute(sub)
  ) and
  not in_notebook(e) and
  not in_raises_test(e) and
  not python2_print(e)
}

predicate is_protocol_method_body(ExprStmt stmt) {
  exists(Function method, Class cls, Name protocol |
    stmt.getScope() = method and
    method.getEnclosingScope() = cls and
    cls.getABase() = protocol and
    protocol.getId() = "Protocol"
  )
}

from ExprStmt stmt
where no_effect(stmt.getValue()) and not is_protocol_method_body(stmt)
select stmt, "This statement has no effect."
