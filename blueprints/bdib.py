from flask import Blueprint, render_template, request, session, jsonify, redirect, url_for
from services.llm import answer_question, client
from services.db import mycursor_bdib, mydb_bdib

def create_bdib_blueprint(*, vectorstores, chat_history):
    bdib_bp = Blueprint('bdib_bp', __name__)

    @bdib_bp.route("/")
    def index_bdib():
        chat_history.clear()
        return render_template('index_bdib.html')

    @bdib_bp.route('/index_bdib.html')
    def first_bdib():
        chat_history.clear()
        return render_template('index_bdib.html')

    @bdib_bp.route('/clear_chat_history', methods=['POST'])
    def clear_chat_history_bdib():
        chat_history.clear()
        return jsonify({'message': 'Chat history cleared successfully'})

    @bdib_bp.route('/answer_bdib', methods=['POST'])
    def answer_bdib():
        if request.method == 'POST':
            user_name = request.form['user_question']
            user_email = request.form['user_email']
            session['user_name'] = user_name
            session['user_email'] = user_email
            chat_history.clear()
            if user_name != "":
                return render_template('answer_bdib.html', user_name=user_name)
        return render_template("index_bdib.html")

    @bdib_bp.route('/submit_question_bdib', methods=['POST'])
    def submit_question_bdib():
        if request.method == 'POST':
            ques_input = request.form['quesInput']
            if ques_input != "":
                user_name = session["user_name"]
                session["question"] = ques_input
                return redirect(url_for('bdib_bp.display_result_bdib', user_name=user_name))

    @bdib_bp.route('/result/<user_name>')
    def display_result_bdib(user_name):
        ques_input = session["question"]
        vectorstore = vectorstores["bdib"]
        answer, sources = answer_question(ques_input, vectorstore)
        
        user_name = session["user_name"]
        
        prompt = f"In context of Organic Farming answer this: {ques_input}\n What is the answer and provide meta of the answer in the next line:"
        ChipAnswerText = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        ChipAnswer = ChipAnswerText.choices[0].message.content.strip()

        session["question"] = ques_input
        session["answer"] = answer
        session["ChipAnswer"] = ChipAnswer

        chat_history.append({'question': ques_input, 'answer': answer, 'ChipAnswer': ChipAnswer})
        return render_template('answer_bdib.html', user_name=user_name, chat_history=chat_history)

    @bdib_bp.route("/rating_submission", methods=["POST"])
    def rating_submission_bdib():
        if request.method == "POST":
            rating = request.form["rate"]
            rating2 = request.form["rate2"]
            question = session["question"]
            answer = session["answer"]
            user_name = session["user_name"]
            user_email = session["user_email"]
            ChipAnswer = session["ChipAnswer"]
            
            mycursor_bdib.execute("SELECT * FROM data")
            num_row = len(mycursor_bdib.fetchall())
            sqlFormula = "INSERT INTO data VALUES (%s,%s,%s,%s,%s,%s,%s)"
            toAppend = (num_row + 1, user_email, question, answer, rating, ChipAnswer, rating2)
            mycursor_bdib.execute(sqlFormula, toAppend)
            mydb_bdib.commit()
          
            return render_template('answer_bdib.html', user_name=user_name, question=question, answer=answer, chat_history=chat_history)

    @bdib_bp.route('/show_table')
    def show_table_bdib():
        mycursor_bdib.execute("SELECT * FROM data")
        table_data = mycursor_bdib.fetchall()
        column_headers = ["Sr. No.", "Email ID", "Question", "BDIB Answer", "Rating", "Raw AI Response", "Rating2"]
        return render_template('show_table.html', table_data=table_data, column_headers=column_headers)

    return bdib_bp
