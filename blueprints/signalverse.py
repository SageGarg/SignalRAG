from flask import Blueprint, render_template, request, session, jsonify, redirect, url_for
from services.llm import answer_question, client
from services.db import mycursor, mydb

def create_signalverse_blueprint(*, vectorstores, chat_history):
    signalverse_bp = Blueprint('signalverse_bp', __name__)

    @signalverse_bp.route("/")
    def index():
        chat_history.clear()
        return render_template('index.html')

    @signalverse_bp.route('/index.html')
    def first():
        chat_history.clear()
        return render_template('index.html')

    @signalverse_bp.route('/clear_chat_history', methods=['POST'])
    def clear_chat_history():
        chat_history.clear()
        return jsonify({'message': 'Chat history cleared successfully'})

    @signalverse_bp.route('/answer', methods=['POST'])
    def answer():
        if request.method == 'POST':
            user_name = request.form['user_question']
            user_email = request.form['user_email']
            session['user_name'] = user_name
            session['user_email'] = user_email
            chat_history.clear()
            if user_name != "":
                return render_template('answer.html', user_name=user_name)  
        return render_template("index.html")

    @signalverse_bp.route('/submit_question', methods=['POST'])
    def submit_question():
        if request.method == 'POST':
            ques_input = request.form['quesInput']
            if ques_input != "":
                user_name = session["user_name"]
                session["question"] = ques_input
                return redirect(url_for('signalverse_bp.display_result', user_name=user_name))

    @signalverse_bp.route('/result/<user_name>')
    def display_result(user_name):
        ques_input = session["question"]
        vectorstore = vectorstores["signalVerse"]
        answer, sources = answer_question(ques_input, vectorstore)
        
        user_name = session["user_name"]
        
        prompt = f"In context of traffic signals answer this: {ques_input}\n What is the answer and provide meta of the answer in the next line:"
        ChipAnswerText = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        ChipAnswer = ChipAnswerText.choices[0].message.content.strip()
        
        session["question"] = ques_input
        session["answer"] = answer
        session["ChipAnswer"] = ChipAnswer

        chat_history.append({'question': ques_input, 'answer': answer, 'ChipAnswer': ChipAnswer})
        return render_template('answer.html', user_name=user_name, chat_history=chat_history)
        
    @signalverse_bp.route("/rating_submission", methods=["POST"])
    def rating_submission():
        if request.method == "POST":
            rating = request.form["rate"]
            rating2 = request.form["rate2"]
            question = session["question"]
            answer = session["answer"]
            user_name = session["user_name"]
            user_email = session["user_email"]
            ChipAnswer = session["ChipAnswer"]

            mycursor.execute("SELECT * FROM data")
            num_row = len(mycursor.fetchall())
            sqlFormula = "INSERT INTO data VALUES (%s,%s,%s,%s,%s,%s,%s)"
            toAppend = (num_row + 1, user_email, question, answer, rating, ChipAnswer, rating2)
            mycursor.execute(sqlFormula, toAppend)
            mydb.commit()
        
            return render_template('answer.html', user_name=user_name, question=question, answer=answer, chat_history=chat_history)

    return signalverse_bp
